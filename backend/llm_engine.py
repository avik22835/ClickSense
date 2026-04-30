import base64
from google import genai
from google.genai import types

from models import ActionRequest, ActionResponse
from prompts import (
    SYSTEM_PROMPT, EXPLANATION_PARAM_DESC, ELEMENT_PARAM_DESC, VALUE_PARAM_DESC,
    BROWSER_ACTION_FUNC_DESC, BROWSER_ACTION_SCHEMA_ACTION_DESC, BROWSER_ACTION_REQUIRED_PROPS,
    ELEMENTLESS_GROUNDING_TRIGGER, ELEMENTLESS_ACTION_PROMPT,
    build_planning_prompt, build_grounding_prompt, format_choices, get_index_from_option_name,
    fuzzy_match_option,
)

MODEL = "gemini-2.5-flash"
VALID_ACTIONS = {"CLICK", "TYPE", "SELECT", "PRESS_ENTER", "SCROLL_UP", "SCROLL_DOWN", "HOVER", "TERMINATE", "NONE"}

BROWSER_ACTION_DECL = types.FunctionDeclaration(
    name="browser_action",
    description=BROWSER_ACTION_FUNC_DESC,
    parameters=types.Schema(
        type=types.Type.OBJECT,
        properties={
            "explanation": types.Schema(
                type=types.Type.STRING,
                description=EXPLANATION_PARAM_DESC,
            ),
            "element": types.Schema(
                type=types.Type.STRING,
                description=ELEMENT_PARAM_DESC,
                nullable=True,
            ),
            "action": types.Schema(
                type=types.Type.STRING,
                description=BROWSER_ACTION_SCHEMA_ACTION_DESC
                    + "; possible values are: CLICK, TYPE, SELECT, PRESS_ENTER, SCROLL_UP, SCROLL_DOWN, HOVER, TERMINATE, NONE",
            ),
            "value": types.Schema(
                type=types.Type.STRING,
                description=VALUE_PARAM_DESC,
                nullable=True,
            ),
        },
        required=BROWSER_ACTION_REQUIRED_PROPS,
    ),
)

BROWSER_TOOL = types.Tool(function_declarations=[BROWSER_ACTION_DECL])

SAFETY_SETTINGS = [
    types.SafetySetting(
        category="HARM_CATEGORY_DANGEROUS_CONTENT",
        threshold="BLOCK_ONLY_HIGH",
    )
]


def _image_part(data_url: str) -> types.Part:
    if not data_url:
        return types.Part(text="[No screenshot available]")
    if "," in data_url:
        header, b64_data = data_url.split(",", 1)
        mime_type = header.split(":")[1].split(";")[0] if ":" in header else "image/png"
    else:
        b64_data = data_url
        mime_type = "image/png"
    image_bytes = base64.b64decode(b64_data)
    return types.Part(inline_data=types.Blob(mime_type=mime_type, data=image_bytes))


def run_pipeline(request: ActionRequest, api_key: str) -> ActionResponse:
    client = genai.Client(api_key=api_key)
    img = _image_part(request.screenshot)

    # ── Step 1: Planning (free-form text, no tool use) ────────────────────────
    planning_prompt = build_planning_prompt(
        request.task, request.history, request.user_message,
        request.rejection_info, request.viewport,
    )

    planning_response = client.models.generate_content(
        model=MODEL,
        contents=[types.Content(parts=[img, types.Part(text=planning_prompt)])],
        config=types.GenerateContentConfig(
            system_instruction=SYSTEM_PROMPT,
            tools=[BROWSER_TOOL],
            tool_config=types.ToolConfig(
                function_calling_config=types.FunctionCallingConfig(mode="NONE")
            ),
            max_output_tokens=2048,
            temperature=0,
            thinking_config=types.ThinkingConfig(thinking_budget=0),
            safety_settings=SAFETY_SETTINGS,
        ),
    )

    planning_output = ""
    if planning_response.candidates:
        for part in planning_response.candidates[0].content.parts:
            if part.text:
                planning_output = part.text
                break

    # ── Step 2: Grounding (force browser_action tool call) ────────────────────
    if ELEMENTLESS_GROUNDING_TRIGGER in planning_output:
        grounding_prompt_text = ELEMENTLESS_ACTION_PROMPT
    else:
        choices = []
        if request.candidate_ids and request.elements:
            choices = format_choices(request.elements, request.candidate_ids, request.viewport)
        grounding_prompt_text = build_grounding_prompt(choices)

    grounding_response = client.models.generate_content(
        model=MODEL,
        contents=[
            types.Content(role="user", parts=[img, types.Part(text=planning_prompt)]),
            types.Content(role="model", parts=[types.Part(text=planning_output)]),
            types.Content(role="user", parts=[types.Part(text=grounding_prompt_text)]),
        ],
        config=types.GenerateContentConfig(
            system_instruction=SYSTEM_PROMPT,
            tools=[BROWSER_TOOL],
            tool_config=types.ToolConfig(
                function_calling_config=types.FunctionCallingConfig(
                    mode="ANY",
                    allowed_function_names=["browser_action"],
                )
            ),
            max_output_tokens=1024,
            temperature=0,
            thinking_config=types.ThinkingConfig(thinking_budget=0),
            safety_settings=SAFETY_SETTINGS,
        ),
    )

    args = None
    if grounding_response.candidates:
        for part in grounding_response.candidates[0].content.parts:
            if part.function_call:
                args = dict(part.function_call.args)
                break

    if not args:
        return ActionResponse(
            action="NONE",
            explanation="AI did not return a valid action. Please try again.",
            planning_output=planning_output or "No planning output available.",
            severity="SAFE",
        )

    explanation = str(args.get("explanation", ""))
    raw_action  = str(args.get("action", "NONE")).upper()
    action      = raw_action if raw_action in VALID_ACTIONS else "NONE"
    value       = args.get("value") or None
    raw_elem    = args.get("element")

    element_index: int | None = None
    if raw_elem and action not in {"PRESS_ENTER", "TERMINATE", "NONE"}:
        letter_idx = get_index_from_option_name(str(raw_elem))
        if letter_idx is not None and 0 <= letter_idx < len(request.candidate_ids):
            element_index = request.candidate_ids[letter_idx]

    if action == "SELECT" and element_index is not None and value:
        target_el = request.elements[element_index]
        if "Options: " in target_el.description:
            try:
                options_part = target_el.description.split("Options: ")[1]
                available_options = [o.strip() for o in options_part.split("|")]
                best_val = fuzzy_match_option(value, available_options)
                if best_val:
                    value = best_val
            except Exception:
                pass

    # ── Step 2.5: Classify noop ───────────────────────────────────────────────
    is_noop = False
    noop_reason: str | None = None
    none_of_above_letter_idx = len(request.candidate_ids)
    raw_letter_idx = get_index_from_option_name(str(raw_elem)) if raw_elem else None
    action_needs_no_element = action in {"SCROLL_UP", "SCROLL_DOWN", "PRESS_ENTER", "TERMINATE", "NONE"}

    if action == "TERMINATE":
        pass
    elif action == "NONE":
        # Never treat as noop — surface to user as an "AI Response" card.
        # The AI outputs NONE when it needs to ask the user something (e.g. "what
        # database ID do you want?"). Silently reprompting is wrong; the user must
        # see the question and reply via the chat box.
        pass
    elif not action_needs_no_element and (raw_letter_idx is None or raw_letter_idx > none_of_above_letter_idx):
        is_noop = True
        noop_reason = "INVALID_ELEMENT"
    elif not action_needs_no_element and raw_letter_idx == none_of_above_letter_idx:
        is_noop = True
        noop_reason = "ACTION_INCOMPATIBLE_WITH_NONE_OF_ABOVE"
    elif action in {"SCROLL_UP", "SCROLL_DOWN"}:
        targets_container = (
            element_index is not None
            and element_index < len(request.elements)
            and request.elements[element_index].isScrollableContainer
        )
        if not targets_container:
            vp = request.viewport
            if action == "SCROLL_UP" and vp.scrollY <= 1:
                is_noop = True
                noop_reason = "AI_SELECTED_NONSENSICAL_SCROLL"
            elif action == "SCROLL_DOWN":
                at_bottom = abs(vp.pageScrollHeight - vp.height - vp.scrollY) < 1
                if at_bottom:
                    is_noop = True
                    noop_reason = "AI_SELECTED_NONSENSICAL_SCROLL"

    if is_noop:
        return ActionResponse(
            action=action,
            element_index=element_index,
            value=value,
            explanation=explanation,
            planning_output=planning_output,
            severity="SAFE",
            is_noop=True,
            noop_reason=noop_reason,
        )

    # Step 3 (safety monitoring) omitted — guidance mode means the human is always
    # the final approver before any action executes, so a second AI safety call adds
    # latency with no benefit.
    return ActionResponse(
        action=action,
        element_index=element_index,
        value=value,
        explanation=explanation,
        planning_output=planning_output,
        severity="SAFE",
    )

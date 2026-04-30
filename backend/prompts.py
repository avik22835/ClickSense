from models import ElementData, ViewportInfo

ELEMENTLESS_GROUNDING_TRIGGER = "SKIP_ELEMENT_SELECTION"

SYSTEM_PROMPT = """You are ClickSense, a step-by-step web guidance assistant. The user is watching their own browser and will do each action themselves — you tell them exactly what to do and why, in plain English.

CRITICAL RULE — FORM PAGES: When you land on a page containing form fields for the FIRST TIME (i.e. the fields are empty or at defaults), your first action must be NONE with a thorough explanation:
1. State what this page/section is for (1 sentence).
2. Go through EVERY visible field/setting one by one: its label, its current value, what it means in plain English, and whether the user should change it (and to what value).
3. End with "Fill in all fields as described above, then click 'Got it, continue' when you're done."

HOWEVER — if you look at the screenshot and the form fields are ALREADY FILLED IN by the user (values entered, options selected, checkboxes ticked), you MUST NOT output NONE again. Instead, immediately output CLICK on the most appropriate submit/action button (e.g. "Create", "Save", "Next", "Continue", "Submit"). Do NOT explain the form again — it is already done.

NEVER skip fields on first visit. NEVER just say "defaults are fine" without listing what the defaults actually are.

ONLY use TYPE or SELECT when there is a single isolated input field (e.g. a search bar, a standalone text field, or a single dropdown on an otherwise empty page). When a page has 2 or more fillable fields that are still empty, ALWAYS use NONE and explain everything — never TYPE into individual fields one at a time.

NAVIGATION RULE: If the task requires going to a section or service and there is no direct link visible on the current page, your very next action MUST be to open the main navigation menu — typically the hamburger/menu icon (☰) in the top-left header or the side-nav drawer toggle. Do NOT fall back to a search bar, "View all products", "All services", "Browse catalog", or any discovery/catalog tile — those are not the canonical navigation path. The nav menu is always the right fallback when a direct link is absent.

Action types: CLICK, SELECT, TYPE, PRESS_ENTER, SCROLL_UP, SCROLL_DOWN, HOVER, TERMINATE, NONE.
- TYPE/SELECT: only for single isolated fields. Always specify the exact text or option value.
- TERMINATE: only when a success/confirmation page confirms the task is fully done.
- NONE: use for full-form explanation, for answering user questions, or when genuinely stuck."""


QUESTION_DESC = """The screenshot below shows the webpage you see. Follow the following guidance to think step by step before outlining the next action step at the current stage:

(Current Webpage Identification)
Firstly, think about what the current webpage is.

(Previous Action Analysis)
Secondly, combined with the screenshot, analyze each step of the previous action history and their intention one by one. Particularly, pay more attention to the last step, which may be more related to what you should do now as the next step. Specifically, if the last action involved a TYPE, always evaluate whether it necessitates a confirmation step, because typically a single TYPE action does not make effect. (often, simply pressing 'Enter', assuming the default element involved in the last action, unless other clear elements are present for operation).

(Screenshot Details Analysis)
Closely examine the screenshot to check the status of every part of the webpage to understand what you can operate with and what has been set or completed. You should closely examine the screenshot details to see what steps have been completed by previous actions even though you are given the textual previous actions. Because the textual history may not clearly and sufficiently record some effects of previous actions, you should closely evaluate the status of every part of the webpage to understand what you have done.

(Form / Page Context Analysis)
If the current page contains ANY form fields, checkboxes, dropdowns, text inputs, or settings: list EVERY one you can see. For each: (a) its label/name, (b) its current value or state (checked/unchecked, selected option, typed text), (c) whether the user needs to change it and to what value, (d) a plain-English explanation of what it controls. Do NOT summarize groups of fields together. Do NOT skip any field. This detailed analysis is essential — it will be used to write the user-facing guidance.

(Next Action Based on Webpage and Analysis)
Then, based on your analysis, in conjunction with human web browsing habits and the logic of web design, decide on the following action.

NAVIGATION RULE: If the task requires navigating to a section or service and no direct link is visible on the current page, your very next action MUST be to open the main navigation menu — typically the hamburger/menu icon (☰) in the top-left header or the side-nav drawer toggle. Do NOT use a search bar, "View all products", "All services", "Browse catalog", or any discovery tile as a substitute. The nav menu is always the correct fallback when a direct link is absent.

FORM RULE: Look closely at the screenshot.
- If the form fields are EMPTY or at defaults (user has not filled them yet) → action MUST be NONE. Explain every field in detail. Do NOT click any button yet.
- If the form fields are ALREADY FILLED IN (you can see values typed, options selected, checkboxes ticked in the screenshot) → action MUST be CLICK on the submit/action button (e.g. "Create", "Save", "Next", "Continue"). Do NOT output NONE again — the user has already filled the form.
Never use TYPE or SELECT on multi-field pages. Only TYPE/SELECT for a single isolated input (e.g. a standalone search box).

To be successful, it is important to follow the following rules:
1. You should only issue a valid action given the current observation.
2. You should only issue one action at a time.
3. For handling the select dropdown elements on the webpage, it's not necessary for you to provide completely accurate options right now. The full list of options for these elements will be supplied later.

Sometimes the very next action won't require a target element: SCROLL_UP, SCROLL_DOWN, TERMINATE, or NONE.
If the very next action won't require a target element, it is very important that you include the exact string SKIP_ELEMENT_SELECTION near the end of your initial/planning output. However, it is equally important that you not include that string if the next action _does_ require a target element."""


REFERRING_PROMPT_DESC = """(Reiteration)
First, reiterate your next target element, its detailed location, and the corresponding operation.

(Multichoice Question)
Below is a multi-choice question, where the choices are elements in the webpage. All elements are arranged in the order based on their height on the webpage, from top to bottom (and from left to right). This arrangement can be used to locate them.
From the screenshot, find out where and what each one is on the webpage, taking into account both their text content and HTML details. Then, determine whether one matches your target element. The element described in the planning output might be visible in the screenshot and yet not be listed in the grounding prompt because it was disabled.
Where the list below mentions an element's position, it should be interpreted as the element's position relative to the viewport (and the coordinate values are relative to the viewport's width/height). Likewise, where information about an element's size is provided as "Size: X% x Y%", it should be interpreted as the element's size relative to the viewport's width/height.
If the element you want to interact with is "BELOW viewport", you should scroll down to it before acting on it. Likewise with "ABOVE viewport" and scrolling up.
Please examine the choices one by one. Choose the matching one. If multiple options match your answer, choose the most likely one by re-examining the screenshot, the choices, and your further reasoning."""


TOOL_USE_GROUNDING_INTRO = "To respond, you _must_ call the 'browser_action' tool after reasoning about the provided options. Any response that doesn't call that tool at the end will be rejected! When setting a parameter to null because it's irrelevant, use json syntax for null (no double quotes around the word null)"

ELEMENTLESS_ACTION_PROMPT = (
    TOOL_USE_GROUNDING_INTRO + "\n" +
    "Based on your prior planning, the next action is not specific to an element. \n"
    "    When calling the 'browser_action' tool, the action should be chosen from the options "
    "{SCROLL_UP, SCROLL_DOWN, PRESS_ENTER, TERMINATE, NONE}"
)


BROWSER_ACTION_FUNC_DESC = "mechanism for acting on the web page on the user's behalf"
BROWSER_ACTION_SCHEMA_ACTION_DESC = "the type of the next action that should be taken"
BROWSER_ACTION_REQUIRED_PROPS = ["explanation", "element", "action", "value"]

EXPLANATION_PARAM_DESC = """Write a thorough, helpful instruction for the human user in second person. REQUIRED FORMAT:

For FORM/SETTINGS pages (action is NONE) — your explanation MUST include ALL of the following:
• One sentence naming what this page or section is for.
• For EACH visible field or setting: its label, its current value, what it means in plain English, and whether to leave it or change it (and to what value). Do NOT group fields together vaguely — name each one individually.
• End with: "Fill in all fields as described above, then click 'Got it, continue' when you're done."

For SINGLE-FIELD steps (action is TYPE or SELECT) — say what to type/select and why.

For NAVIGATION/BUTTON steps (no form fields) — 2-3 sentences: what the button/link does, why it is the right next step, and any important context.

Rules: Always second person ("Click...", "Type...", "Leave X as Y because..."). Never first person. Never say "default settings are fine" without listing what those defaults are. Never skip visible fields."""

ELEMENT_PARAM_DESC = "The one-or-two-uppercase-letters ID of your chosen element. (can be set to null for PRESS_ENTER, SCROLL_UP, SCROLL_DOWN, or TERMINATE); if the element's ID is just 1 letter, you must only put that 1 letter ID here and not double it to a 2 letter ID."

VALUE_PARAM_DESC = """Provide additional input based on action. The value means:
    - If action == TYPE, specify the text to be typed.
    - If action == SELECT, indicate the option to be chosen. Revise the selection value to align with the available options within the element.
    - If action == CLICK, PRESS_ENTER, SCROLL_UP, SCROLL_DOWN, TERMINATE or NONE, set this to null."""


# ── Action Judgment (Monitoring) ───────────────────────────────────────────────

ACTION_JUDGMENT_FUNC_DESC = "mechanism for submitting an assessment of the potential state-changing nature of an action"
ACTION_JUDGMENT_SEVERITY_PARAM_DESC = "whether the proposed action's state-change is LOW, MEDIUM, or HIGH severity (or SAFE if it isn't meaningfully state-changing)"
ACTION_JUDGMENT_EXPLANATION_PARAM_DESC = "a 1-sentence explanation of why the proposed action belongs to the chosen state-change severity level."
ACTION_JUDGMENT_REQUIRED_PROPS = ["severity", "explanation"]

AUTO_MONITOR_PROMPT_INTRO = """The proposed action (above, under "GROUNDING:") is potentially state-changing and may require human confirmation. Please review the proposed action, in the context of the earlier task specification, screenshot, and planning output.
Think step by step about whether this action _on its own_ could have any effects (especially hard-to-reverse effects) which the user might conceivably not desire or even just not want to be surprised by.
The definitions of the levels of state-change severity of actions are:
- LOW: These actions impact solely the individual or immediate surroundings without enduring or substantial effects on others. They are frequently reversible and entail minimal to no legal responsibility or ethical implications. For example, changing a website's theme, adding an item to your wishlist on a website, opting out of marketing emails from one source, or disabling a website's ad-targeting cookies.
- MEDIUM: These actions entail engaging with others. They may affect the user's reputation, establish precedents, or shape minor decisions and behaviors of others. They are often partly but not fully reversible; for example, the user could delete a comment, tweet, or direct message in most cases, but others might've already seen and/or screen-captured it. Other examples include scheduling or joining a meeting, creating or joining a group chat, or sending an email. The email case is notable for being even less reversible (the user can only send a follow-up email to explain and apologize) than other Medium-severity actions while not qualifying as High severity.
On the other hand, archiving a post, task, file, etc. in a shared space is entirely reversible but in the meantime may confuse or distress the other users of the space (and retrieving the item from archival storage may require the mutual inconvenience of getting help from an administrator).
- HIGH: These actions have consequences that are significant and very difficult to reverse or even infeasible to reverse. This includes any financial transactions and other actions (purchases, loan applications, online betting, etc.). It also includes legal commitments (e.g. agreeing to a contract to make an account on a website) or legally risky actions (like publicly sharing proprietary information).
Meanwhile, deleting any file, post, task, message, etc. in a way that cannot feasibly be reversed also qualifies as a High severity action. This only applies to the deletion of an existing thing that had not just been created by the agent (to accord with the common-sense judgment that the agent reversing its own mistake from a moment before is not itself a dangerous action).
- SAFE: These actions have no lasting impact on the world of any significance and any short-term effects are trivial to reverse. For example, consider clicking a button to go to another page: this changes the state of the local browser, but that change is ephemeral and un-concerning; likewise, it may cause writes to the website's traffic analytics database (which the user cannot reverse), but that state change is not significant for users.
You should make your judgement solely about the current proposed action (above, under "GROUNDING:"), not being swayed by the riskiness of the task (specified earlier) or any possible effects that this action could add to future actions.
"""

AUTO_MONITOR_PROMPT_WITH_TOOL_USE_CONCLUSION = "To respond, you _must_ call the 'action_judgment' tool after reasoning about the proposed action. Any response that doesn't call that tool at the end will be rejected!"


# ── Option name helpers (mirrors format_prompt_utils.ts) ──────────────────────

def _generate_option_name(index: int) -> str:
    if index < 26:
        return chr(65 + index)
    elif index < 702:
        first_letter_index = index // 26 - 1
        second_letter_index = index % 26
        return chr(65 + first_letter_index) + chr(65 + second_letter_index)
    else:
        raise ValueError("index out of range")


def get_index_from_option_name(opt_name: str | None) -> int | None:
    if not opt_name:
        return None
    upper = opt_name.upper()
    if not upper.isalpha() or len(upper) not in (1, 2):
        return None
    if len(upper) == 1:
        return ord(upper) - ord('A')
    else:
        return (ord(upper[0]) - ord('A') + 1) * 26 + (ord(upper[1]) - ord('A'))


def fuzzy_match_option(target: str, options: list[str], threshold: int = 70) -> str | None:
    if not target or not options:
        return None
    target_lower = target.lower()
    for opt in options:
        if opt.lower() == target_lower:
            return opt
    try:
        from thefuzz import fuzz, process
        matches = process.extract(target, options, scorer=fuzz.token_sort_ratio, limit=1)
        if matches and matches[0][1] >= threshold:
            return matches[0][0]
    except Exception:
        pass
    return None


def format_choices(elements: list[ElementData], candidate_ids: list[int], viewport: ViewportInfo) -> list[str]:
    choices = []
    for elem_idx in candidate_ids:
        elem = elements[elem_idx]
        tag_head = elem.tagHead or elem.tagName
        tag_name = elem.tagName

        rel_x = 100 * elem.centerCoords[0] / viewport.width if viewport.width else 0
        rel_y = 100 * elem.centerCoords[1] / viewport.height if viewport.height else 0
        rel_w = 100 * elem.width / viewport.width if viewport.width else 0
        rel_h = 100 * elem.height / viewport.height if viewport.height else 0

        if rel_y < 0:
            position_info = "ABOVE viewport"
            size_info = ""
        elif rel_y > 100:
            position_info = "BELOW viewport"
            size_info = ""
        elif rel_x < 0:
            position_info = "LEFT of viewport"
            size_info = ""
        elif rel_x > 100:
            position_info = "RIGHT of viewport"
            size_info = ""
        else:
            position_info = f"Position: {rel_x:.1f}% from left, {rel_y:.1f}% from top"
            size_info = f"Size: {rel_w:.1f}% x {rel_h:.1f}%; "

        desc_words = elem.description.split()
        if tag_name != "select" and len(desc_words) >= 30:
            desc = " ".join(desc_words[:29]) + "..."
        else:
            desc = elem.description

        choices.append(f"{position_info}; {size_info}Element: <{tag_head}>{desc}</{tag_name}>")
    return choices


def _format_options(choices: list[str]) -> str:
    none_of_above = _generate_option_name(len(choices))
    result = (
        f"If none of these elements match your target element, please select {none_of_above}. "
        "None of the other options match the correct element.\n"
    )
    result += "".join(f"{_generate_option_name(i)}. {choice}\n" for i, choice in enumerate(choices))
    result += f"{none_of_above}. None of the other options match the correct element\n\n"
    return result


def build_planning_prompt(task: str, history: list[str], user_message: str | None,
                           rejection_info: str | None, viewport: ViewportInfo | None = None) -> str:
    query_text = "You are asked to complete the following task: " + task + "\n\nPrevious Actions:\n"
    if not history:
        query_text += "No prior actions\n"
    else:
        query_text += "\n".join(history) + "\n"

    query_text += "\n" + QUESTION_DESC

    if viewport is not None:
        scrollable_distance = viewport.pageScrollHeight - viewport.height
        if scrollable_distance > 0:
            scroll_pct = 100 * viewport.scrollY / scrollable_distance
            query_text += f"\nViewport is scrolled {scroll_pct:.1f}% down the page."

    if rejection_info:
        query_text += f"\n\n{rejection_info}"

    if user_message:
        query_text += (
            f'\n\nUSER MESSAGE: "{user_message}"\n'
            "If this is a question or request for explanation, answer it thoroughly in your planning output "
            "and output action NONE (do not take any browser action). "
            "If it is a command or direction, take the appropriate browser action instead."
        )

    return query_text


def build_grounding_prompt(choices: list[str]) -> str:
    return REFERRING_PROMPT_DESC + "\n\n" + _format_options(choices) + TOOL_USE_GROUNDING_INTRO

from pydantic import BaseModel


class ElementData(BaseModel):
    description: str = ""
    tagName: str = ""
    tagHead: str = ""
    width: float = 0
    height: float = 0
    centerCoords: list[float] = [0, 0]
    isScrollableContainer: bool = False


class ViewportInfo(BaseModel):
    width: int
    height: int
    scrollX: float = 0
    scrollY: float = 0
    pageScrollWidth: float = 0
    pageScrollHeight: float = 0


class ActionRequest(BaseModel):
    screenshot: str                      # base64 data URL (data:image/png;base64,...)
    elements: list[ElementData]
    candidate_ids: list[int]
    task: str
    history: list[str] = []
    viewport: ViewportInfo
    user_message: str | None = None
    rejection_info: str | None = None
    options: dict = {}


class ActionResponse(BaseModel):
    action: str                          # CLICK, TYPE, SELECT, SCROLL_UP, SCROLL_DOWN, PRESS_ENTER, NONE, TERMINATE
    element_index: int | None = None
    value: str | None = None
    explanation: str
    planning_output: str
    severity: str = "SAFE"              # SAFE, LOW, MEDIUM, HIGH
    is_noop: bool = False
    noop_reason: str | None = None

from typing import Optional

from .errors import AppError


TIE_BAD = "tie_bad"
TIE_GOOD = "tie_good"
TIE_RESULTS = (TIE_BAD, TIE_GOOD)


def resolve_vote_choice(choice: Optional[str], v_left: str, v_right: str) -> str:
    if choice == "left":
        return v_left
    if choice == "right":
        return v_right
    if choice in TIE_RESULTS:
        return choice
    raise AppError("无效评测选项")

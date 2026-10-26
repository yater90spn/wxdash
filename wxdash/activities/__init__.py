from .running import Running
from .sailing import Sailing
from .spectator import Spectator
from .surf import Surf
from .yardwork import Yardwork

REGISTRY = {
    "spectator": Spectator,
    "baseball": Spectator,   # alias
    "surf": Surf,
    "sailing": Sailing,
    "running": Running,
    "yardwork": Yardwork,
}

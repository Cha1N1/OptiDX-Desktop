"""Read-only background discovery, bound to the originating game and request."""

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal, Slot


class Result(QObject):
    ready = Signal(object, int, object)


class Discovery(QRunnable):
    def __init__(self, game, generation):
        super().__init__()
        self.game = game
        self.generation = generation
        self.result = Result()

    def run(self):
        from .features import dll_locations

        try:
            value = dll_locations(self.game)
        except (OSError, ValueError) as error:
            value = str(error)
        self.result.ready.emit(self.game, self.generation, value)


class DiscoveryController(QObject):
    def __init__(self, window, destination):
        super().__init__(window)
        self.window = window
        self.destination = destination
        self.generation = 0
        self.pending = {}

    def start(self, game):
        self.generation += 1
        task = Discovery(game, self.generation)
        self.pending[self.generation] = task
        task.result.ready.connect(self.finished)
        QThreadPool.globalInstance().start(task)

    @Slot(object, int, object)
    def finished(self, game, generation, value):
        self.pending.pop(generation, None)
        if self.window.selected != game or self.generation != generation:
            return
        self.destination.setPlainText(
            value
            if isinstance(value, str)
            else "\n".join(value) or "No existing DLSS/Streamline DLLs detected."
        )


def discover_dlls(window, game, destination):
    if not hasattr(window, "dll_discovery"):
        window.dll_discovery = DiscoveryController(window, destination)
    window.dll_discovery.start(game)

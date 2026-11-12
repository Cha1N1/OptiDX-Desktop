"""Launching games through stores or detached profile wrappers."""

from .runtime import open_game_uri, python_executable


class GameLaunchMixin:
    def launch(self):
        if self.selected and self.selected.launch_uri:
            try:
                open_game_uri(self.selected)
            except OSError as error:
                self.report_error(f"Could not start {self.selected.store}: {error}")
        elif self.selected:
            self.launch_manual()

    def launch_manual(self):
        game = self.selected
        if game.id in self.launch_processes:
            return
        try:
            if self.save_profile() is False:
                return
            from .launch import runner_command, profile_entry_arguments
            import os

            profile = self.repository.preferences(game)
            command = runner_command(game, profile)
            path = self.repository.directory / "profiles" / (game.id + ".json")
            if game.store == "Bottles" and not profile.get("runner_command"):
                profile["runner_kind"] = "bottles"
                self.repository.save_preferences(game, profile)
            image = os.environ.get("APPIMAGE")
            program = image or python_executable()
            from .runtime import appimage_arguments

            arguments = (
                [*appimage_arguments(), "--launch-profile", str(path), "--", *command]
                if image
                else [
                    "-B",
                    *profile_entry_arguments(path),
                    "--",
                    *command,
                ]
            )
            self.start_game_process(game, program, arguments)
        except Exception as error:
            self.report_error(str(error))

    def start_game_process(self, game, program, arguments):
        """Start the launch wrapper detached so closing this window never stops a game."""
        from .launch import _process_token

        log = self.repository.directory / "logs" / f"launch-{game.id}.log"
        log.parent.mkdir(parents=True, exist_ok=True)
        import subprocess

        with log.open("wb") as output:
            process = subprocess.Popen(
                [program, *arguments],
                cwd=game.target,
                stdin=subprocess.DEVNULL,
                stdout=output,
                stderr=subprocess.STDOUT,
                start_new_session=True,
            )
        pid = process.pid
        # Children of this window are reaped here; restored records use /proc.
        self.launch_children[game.id] = process
        self.launch_processes[game.id] = {
            "pid": pid,
            "token": _process_token(pid),
            "title": game.title,
            "log": str(log),
        }
        self.save_running_games()
        self.log.appendPlainText(f"Started {game.title}; wrapper output: {log}")
        self.running_timer.start()
        self.populate()

    def save_running_games(self):
        from .storage import atomic_json

        atomic_json(self.repository.directory / "running.json", self.launch_processes)

    def restore_running_games(self):
        """Keep the running indicator for games started before this window opened."""
        from .launch import process_running
        from .storage import read_json

        try:
            records = read_json(self.repository.directory / "running.json", {})
        except ValueError:
            records = {}
        self.launch_processes = {
            key: record
            for key, record in (records if isinstance(records, dict) else {}).items()
            if isinstance(record, dict) and process_running(record.get("pid"), record.get("token"))
        }
        if self.launch_processes:
            self.running_timer.start()

    def poll_running_games(self):
        from .launch import process_running

        finished = [
            key
            for key, record in self.launch_processes.items()
            if (
                self.launch_children[key].poll() is not None
                if key in self.launch_children
                else not process_running(record["pid"], record.get("token"))
            )
        ]
        for key in finished:
            self.launch_finished(key)
        if not self.launch_processes:
            self.running_timer.stop()

    def launch_finished(self, game_id):
        record = self.launch_processes.pop(game_id, None)
        self.launch_children.pop(game_id, None)
        if record:
            self.save_running_games()
            self.log.appendPlainText(
                f"{record.get('title', 'Game')} exited; wrapper output: {record.get('log')}"
            )
            self.populate()

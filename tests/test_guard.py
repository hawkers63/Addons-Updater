# ==============================================================================
# ESO Addons Updater
# Proprietary — Copyright (c) 2026 Mark Hawksworth (hawkers63). All Rights Reserved.
#
# This software and associated documentation files are proprietary and confidential.
# Unauthorised copying, distribution, modification, reproduction, or commercial
# use of this software, via any medium, is strictly prohibited without the express
# prior written permission of the copyright holder.
# ==============================================================================
"""The game-running warning shown before a package is applied. No real process is queried."""

import subprocess
import types
import unittest
from unittest import mock

from support import app

RUNNING = "eso64.exe                    12345 Console                    1    1,234,567 K\n"
CLOSED = "INFO: No tasks are running which match the specified criteria.\n"


class IsEsoRunningTests(unittest.TestCase):
    @staticmethod
    def check(**behaviour):
        with mock.patch.object(app.subprocess, "check_output", **behaviour) as call:
            return app.is_eso_running(), call

    def test_detects_the_client_in_any_letter_case(self):
        for output in (RUNNING, RUNNING.upper()):
            with self.subTest(output=output[:9]):
                running, _ = self.check(return_value=output)
                self.assertTrue(running)

    def test_reports_a_closed_game(self):
        running, _ = self.check(return_value=CLOSED)
        self.assertFalse(running)

    def test_runs_tasklist_without_a_console_window_and_with_a_timeout(self):
        _, call = self.check(return_value=CLOSED)
        command = call.call_args.args[0]
        self.assertEqual(command[0], "tasklist")
        self.assertIn("IMAGENAME eq eso64.exe", command)
        self.assertEqual(call.call_args.kwargs["creationflags"], 0x08000000)
        self.assertLessEqual(call.call_args.kwargs["timeout"], 10)

    def test_fails_open_when_tasklist_cannot_run(self):
        failures = (FileNotFoundError("tasklist"), OSError("blocked"),
                    subprocess.TimeoutExpired("tasklist", 5),
                    subprocess.CalledProcessError(1, "tasklist"))
        for failure in failures:
            with self.subTest(failure=type(failure).__name__):
                running, _ = self.check(side_effect=failure)
                self.assertFalse(running)


class VerifyGameClosedTests(unittest.TestCase):
    def test_a_closed_game_needs_no_prompt(self):
        with mock.patch.object(app, "is_eso_running", return_value=False), \
                mock.patch.object(app.messagebox, "askyesno") as ask:
            self.assertTrue(app.verify_game_closed("window"))
        ask.assert_not_called()

    def test_a_running_game_asks_and_returns_the_answer_with_no_as_the_default(self):
        for answer in (True, False):
            with self.subTest(answer=answer):
                with mock.patch.object(app, "is_eso_running", return_value=True), \
                        mock.patch.object(app.messagebox, "askyesno", return_value=answer) as ask:
                    self.assertIs(app.verify_game_closed("window"), answer)
                options = ask.call_args.kwargs
                self.assertEqual((options["default"], options["icon"], options["parent"]),
                                 (app.messagebox.NO, "warning", "window"))
                self.assertIn("eso64.exe", options["message"])


class PreviewApplyTests(unittest.TestCase):
    """PackagePreview.apply is exercised through a stand-in, so no window is needed."""

    @staticmethod
    def stand_in(selected=("Alpha",)):
        boxes = {name: types.SimpleNamespace(get=lambda: True) for name in selected}
        application = types.SimpleNamespace(preview="open preview", install=mock.Mock())
        return types.SimpleNamespace(boxes=boxes, app=application, package="p.zip",
                                     entries=("row",), temporary=None, destroy=mock.Mock())

    @staticmethod
    def apply(stand_in, *, game_closed):
        with mock.patch.object(app, "verify_game_closed", return_value=game_closed) as guard:
            app.PackagePreview.apply(stand_in)
        return guard

    def test_declining_the_warning_keeps_the_preview_open_and_installs_nothing(self):
        stand_in = self.stand_in()
        guard = self.apply(stand_in, game_closed=False)
        guard.assert_called_once_with(stand_in)
        stand_in.destroy.assert_not_called()
        stand_in.app.install.assert_not_called()
        self.assertEqual(stand_in.app.preview, "open preview")

    def test_proceeding_closes_the_preview_and_installs_the_selection(self):
        stand_in = self.stand_in(("Alpha", "Beta"))
        self.apply(stand_in, game_closed=True)
        stand_in.destroy.assert_called_once_with()
        stand_in.app.install.assert_called_once_with("p.zip", ("row",), ("Alpha", "Beta"), None)
        self.assertIsNone(stand_in.app.preview)

    def test_an_empty_selection_never_reaches_the_guard(self):
        stand_in = self.stand_in(())
        with mock.patch.object(app.messagebox, "showinfo") as info:
            guard = self.apply(stand_in, game_closed=True)
        guard.assert_not_called()
        info.assert_called_once()
        stand_in.app.install.assert_not_called()

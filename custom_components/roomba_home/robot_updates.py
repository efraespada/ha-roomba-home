"""Per-device views driven by the shared account refresh."""

from homeassistant.core import callback


class RobotUpdates:
    """Own one robot's state and callbacks without starting another poller."""

    def __init__(self, account, robot_id):
        self.account = account
        self.robot_id = robot_id
        self._callbacks = set()
        self._remove_account_listener = None
        self._last_update = None

    @property
    def state(self):
        return (self.account.data or {}).get(self.robot_id)

    @property
    def last_update_success(self):
        return self.account.last_update_success

    def _snapshot(self):
        return (
            self.state,
            self.last_update_success,
            self.account.profiles.get(self.robot_id),
            self.account.command_status.get(self.robot_id),
            self.account.maps_for_robot(self.robot_id),
        )

    @callback
    def _updated(self):
        snapshot = self._snapshot()
        if snapshot == self._last_update:
            return
        self._last_update = snapshot
        for listener in tuple(self._callbacks):
            listener()

    @callback
    def async_add_listener(self, update_callback, context=None):
        self._callbacks.add(update_callback)
        if self._remove_account_listener is None:
            self._last_update = self._snapshot()
            self._remove_account_listener = self.account.async_add_listener(
                self._updated, self.robot_id
            )

        @callback
        def remove():
            self._callbacks.remove(update_callback)
            if not self._callbacks:
                self._remove_account_listener()
                self._remove_account_listener = None

        return remove

    async def async_request_refresh(self):
        await self.account.async_request_refresh()

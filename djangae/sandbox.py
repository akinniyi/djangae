from datetime import datetime
import os
import subprocess
import logging
import time
from urllib.error import (
    HTTPError,
    URLError,
)
from urllib.request import urlopen

from djangae.environment import get_application_root

_ACTIVE_EMULATORS = {}
_ALL_EMULATORS = ("datastore", "tasks", "storage")


DATASTORE_PORT = 10901
TASKS_PORT = 10908
STORAGE_PORT = 10911


def _launch_process(command_line):
    env = os.environ.copy()
    return subprocess.Popen(command_line.split(" "), env=env)


def _wait_for_tasks(port):
    time.sleep(5)  # FIXME: Need to somehow check it's running


def _wait_for_datastore(port):
    _wait(port, "Cloud Datastore Emulator")


def _wait_for_storage(port):
    _wait(port, "Cloud Storage Emulator")


def _wait(port, service):
    print("Waiting for %s..." % service)

    TIMEOUT = 60.0
    start = datetime.now()

    time.sleep(1)

    failures = 0
    while True:
        try:
            response = urlopen("http://127.0.0.1:%s/" % port)
        except (HTTPError, URLError):
            failures += 1
            time.sleep(1)
            if failures > 5:
                # Only start logging if this becomes persistent
                logging.exception("Error connecting to the %s. Retrying..." % service)
            continue

        if response.status == 200:
            # Give things a second to really boot
            time.sleep(1)
            break

        if (datetime.now() - start).total_seconds() > TIMEOUT:
            raise RuntimeError("Unable to start %s. Please check the logs." % service)

        time.sleep(1)


def start_emulators(persist_data, emulators=None, storage_dir=None):
    emulators = emulators or _ALL_EMULATORS
    storage_dir = storage_dir or os.path.join(get_application_root(), ".storage")

    if "datastore" in emulators:
        os.environ["DATASTORE_EMULATOR_HOST"] = "127.0.0.1:%s" % DATASTORE_PORT
        os.environ["DATASTORE_PROJECT_ID"] = "example"

        # Start the cloud datastore emulator
        command = "gcloud beta emulators datastore start --consistency=1.0 --quiet --project=example"
        command += " --host-port=127.0.0.1:%s" % DATASTORE_PORT

        if not persist_data:
            command += " --no-store-on-disk"

        _ACTIVE_EMULATORS["datastore"] = _launch_process(command)
        _wait_for_datastore(DATASTORE_PORT)

    if "tasks" in emulators:
        os.environ["TASKS_EMULATOR_HOST"] = "127.0.0.1:%s" % TASKS_PORT
        _ACTIVE_EMULATORS["tasks"] = _launch_process(
            "gcloud-tasks-emulator start -q --port=%s" % TASKS_PORT
        )
        _wait_for_tasks(TASKS_PORT)

    if "storage" in emulators:
        os.environ["STORAGE_EMULATOR_HOST"] = "http://127.0.0.1:%s" % STORAGE_PORT
        _ACTIVE_EMULATORS["storage"] = _launch_process(
            "gcloud-storage-emulator start -q --port=%s --no-store-on-disk" % STORAGE_PORT
        )
        _wait_for_storage(STORAGE_PORT)


def stop_emulators(emulators=None):
    emulators = emulators or _ALL_EMULATORS
    for k, v in _ACTIVE_EMULATORS.items():
        if k in emulators:
            v.kill()

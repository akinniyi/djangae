import sys
from djangae import environment
from djangae import debugger


def fix_c_whitelist():
    from djangae.compat import sandbox
    if '_sqlite3' not in sandbox._WHITE_LIST_C_MODULES:
        sandbox._WHITE_LIST_C_MODULES.extend([
            '_sqlite3',
            '_ssl',  # Workaround for App Engine bug #9246
            '_socket',
            '_ctypes'  # Necessary for ptvsd
        ])


# We do this globally for the local environment outside of dev_appserver
if environment.is_development_environment():
    fix_c_whitelist()


_SANDBOX_FIXED = False


def fix_sandbox():
    """
        This is the nastiest thing in the world...

        This WSGI middleware is the first chance we get to hook into anything. On the dev_appserver
        at this point the Python sandbox will have already been initialized. The sandbox replaces stuff
        like the subprocess module, and the select module. As well as disallows _sqlite3. These things
        are really REALLY useful for development.

        So here we dismantle parts of the sandbox. Firstly we add _sqlite3 to the allowed C modules.

        This only happens on the dev_appserver, it would only die on live. Everything is checked so that
        changes are only made if they haven't been made already.
    """

    global _SANDBOX_FIXED

    if environment.is_production_environment() or _SANDBOX_FIXED:
        return

    from djangae.compat import sandbox

    if '_socket' not in sandbox._WHITE_LIST_C_MODULES:
        fix_c_whitelist()

    # Reload the system socket.py, because of bug #9246
    import imp
    import os
    import ast

    sys.modules.pop("socket", None)
    psocket = os.path.join(os.path.dirname(ast.__file__), 'socket.py')
    imp.load_source('socket', psocket)

    _SANDBOX_FIXED = True

class DjangaeApplication(object):

    def __init__(self, application):
        from django.conf import settings
        from django.core.exceptions import ImproperlyConfigured

        for app in settings.INSTALLED_APPS:
            if app.startswith("django."):
                raise ImproperlyConfigured("You must place 'djangae' before any 'django' apps in INSTALLED_APPS")
            elif app == "djangae":
                break

        self.wrapped_app = application

    def __call__(self, environ, start_response):
        fix_sandbox()
        debugger.enable()
        return self.wrapped_app(environ, start_response)


from __future__ import absolute_import

import collections
import functools
import logging
import random
import sys
import time
import warnings
from socket import socket


try:
    # If gcloudc is available, make sure we catch its TransactionFailedError
    from gcloudc.db.transaction import TransactionFailedError
except ImportError:
    class TransactionFailedError:
        pass


try:
    # Try to import the core GoogleAPIError
    from google.api_core.exceptions import GoogleAPIError
except ImportError:
    class GoogleAPIError:
        pass


# No SDK imports allowed in module namespace because `./manage.py runserver`
# imports this before the SDK is added to sys.path. See bugs #899, #1055.
logger = logging.getLogger(__name__)


class DjangaeDeprecation(DeprecationWarning):
    pass


def deprecated(replacement):
    warnings.simplefilter("default", DjangaeDeprecation)

    def wrapper(func):
        @functools.wraps(func)
        def new_func(*args, **kwargs):
            warnings.warn(
                "{} is deprecated. Use {} instead.".format(func.__name__, replacement),
                DjangaeDeprecation, 2
            )
            return func(*args, **kwargs)
        return new_func
    return wrapper


@deprecated(replacement="djangae.environment.application_id")
def application_id():
    from . import environment
    return environment.application_id()


@deprecated(replacement="djangae.environment.sdk_is_available")
def appengine_on_path():
    from . import environment
    return environment.sdk_is_available()


@deprecated(replacement="djangae.environment.is_production_environment")
def on_production():
    from . import environment
    return environment.is_production_environment()


@deprecated(replacement="djangae.environment.datastore_is_available")
def datastore_available():
    from . import environment
    return environment.datastore_is_available()


@deprecated(replacement="djangae.environment.get_application_root")
def find_project_root():
    from . import environment
    return environment.get_application_root()


def in_testing():
    """
        FIXME! This is in the wrong place, and implemented wrongly!

        What should happen is in djangae.core.management.execute_from_command_line
        we should activate the "test" sandbox if we are running the "test" management command.
        This sandbox should (for now) call through to the local sandbox.

        We then need to add a get_active_sandbox() function to sandbox.py, and then
        deprecate this function in favour of "djangae.sandbox.get_active_sandbox"
    """
    return "test" in sys.argv


def get_in_batches(queryset, batch_size=10):
    """ prefetches the queryset in batches """
    start = 0
    if batch_size < 1:
        raise Exception("batch_size must be > 0")
    end = batch_size
    while True:
        batch = [x for x in queryset[start:end]]
        for y in batch:
            yield y
        if len(batch) < batch_size:
            break
        start += batch_size
        end += batch_size


def retry_until_successful(func, *args, **kwargs):
    return retry(func, *args, _attempts=float('inf'), **kwargs)


def _yield(seconds):  # Patchable
    time.sleep(seconds)


def retry(func, *args, **kwargs):
    """ Calls a function that may intermittently fail, catching the given error(s) and (re)trying
        for a maximum of `_attempts` times.
    """

    # Slightly weird `.pop(x, None) or default` thing here due to not wanting to repeat the tuple of
    # default things in `retry_on_error` and having to do inline imports
    catch = kwargs.pop('_catch', None) or (
        GoogleAPIError,
        TransactionFailedError,
    )
    attempts = kwargs.pop('_attempts', 3)
    timeout_ms = kwargs.pop('_initial_wait', 750)  # Try 750, 1500, 3000 etc.
    max_wait = kwargs.pop('_max_wait', 30000)

    # Whether or not to add a random element to the sleep times
    randomize = kwargs.pop('_avoid_clashes', True)

    i = 0
    while True:
        try:
            i += 1
            return func(*args, **kwargs)
        except catch as exc:
            if i >= attempts:
                logger.error("Ran out of attempts while retrying function")
                raise  # Re-raise original exception

            # The location of the errors on each attempt may change, so we log
            # each one
            logger.exception("Exception during retry attempt. Will retry.")

            logger.info("Retrying function: %s(%s, %s) - %s", func, args, kwargs, exc)

            # Add a slight bit of randomness (up to a second) to avoid competing tasks
            # repeatedly clashing with each other on retries. We still cap at max_wait,
            # because that's what the user requested, we also respect initial wait so don't
            # add a random factor on the first sleep
            if randomize:
                random_factor = random.randint(0, 1000) if i > 1 else 0
            else:
                random_factor = 0

            _yield(min((timeout_ms + random_factor), max_wait) * 0.001)
            timeout_ms *= 2
            timeout_ms = min(timeout_ms, max_wait)


def retry_on_error(
    _catch=None, _attempts=3, _initial_wait=375, _max_wait=30000, _avoid_clashes=True
):
    """ Decorator for wrapping a function with `retry`. """

    def decorator(func):
        @functools.wraps(func)
        def replacement(*args, **kwargs):
            return retry(
                func,
                _catch=_catch, _attempts=_attempts,
                _initial_wait=_initial_wait, _max_wait=_max_wait,
                _avoid_clashes=_avoid_clashes,
                *args, **kwargs
            )
        return replacement
    return decorator


def djangae_webapp(request_handler):
    """ Decorator for wrapping a webapp2.RequestHandler to work with
    the django wsgi hander"""

    def request_handler_wrapper(request, *args, **kwargs):
        from webapp2 import Request, Response, WSGIApplication
        from django.http import HttpResponse

        class Route:
            handler_method = request.method.lower()

        req = Request(request.environ)
        req.route = Route()
        req.route_args = args
        req.route_kwargs = kwargs
        req.app = WSGIApplication()
        response = Response()
        view_func = request_handler(req, response)
        view_func.dispatch()

        django_response = HttpResponse(
            response.body, status=int(str(response.status).split(" ")[0])
        )
        for header, value in response.headers.items():
            django_response[header] = value

        return django_response

    return request_handler_wrapper


def port_is_open(url, port):
    s = socket()
    try:
        s.bind((url, int(port)))
        s.close()
        return True
    except Exception:
        return False


def get_next_available_port(url, port):
    for offset in range(10):
        if port_is_open(url, port + offset):
            break
    else:
        raise Exception("Could not find available port between %d and %d", (port, port + offset))
    return port + offset


class memoized(object):
    def __init__(self, func, *args):
        self.func = func
        self.cache = {}
        self.args = args

    def __call__(self, *args):
        args = self.args or args
        if not isinstance(args, collections.Hashable):
            # uncacheable. a list, for instance.
            # better to not cache than blow up.
            return self.func(*args)

        if args in self.cache:
            return self.cache[args]
        else:
            value = self.func(*args)
            self.cache[args] = value
            return value

    def __repr__(self):
        '''Return the function's docstring.'''
        return self.func.__doc__

    def __get__(self, obj, objtype):
        '''Support instance methods.'''
        return functools.partial(self.__call__, obj)

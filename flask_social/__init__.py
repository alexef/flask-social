# -*- coding: utf-8 -*-
"""
    flask.ext.social
    ~~~~~~~~~~~~~~~~

    Flask-Social is a Flask extension that aims to add simple OAuth provider
    integration for Flask-Security

    :copyright: (c) 2012 by Matt Wright.
    :license: MIT, see LICENSE for more details.
"""

try:
    import twitter
except ImportError:
    pass

try:
    import facebook
except ImportError:
    pass

try:
    import httplib2
    import oauth2client.client as googleoauth
    import apiclient.discovery as googleapi
except ImportError:
    pass

try:
    import foursquare
except ImportError:
    pass

from flask import Blueprint, redirect, session, request, current_app
from flask.ext.security import current_user, login_user, login_required
from flask.ext.security.utils import get_post_login_redirect
from flask.ext.oauth import OAuth

from flask_social.core import ConnectionFactory, LoginHandler, ConnectHandler
from flask_social.signals import social_connection_removed, social_login_completed, \
     social_login_failed, social_connection_created, social_connection_failed
from flask_social.utils import get_class_from_string, do_flash, config_value, \
     get_display_name, get_authorize_callback, get_remote_app
from flask_social import exceptions, views


default_config = {
    'SOCIAL_URL_PREFIX': None,
    'SOCIAL_APP_URL': 'http://127.0.0.1:5000',
    'SOCIAL_CONNECT_ALLOW_REDIRECT': '/profile',
    'SOCIAL_CONNECT_DENY_REDIRECT': '/profile',
    'SOCIAL_FLASH_MESSAGES': True,
    'SOCIAL_POST_OAUTH_CONNECT_SESSION_KEY': 'post_oauth_connect_url',
    'SOCIAL_POST_OAUTH_LOGIN_SESSION_KEY': 'post_oauth_login_url'
}

default_provider_config = {
    'twitter': {
        'id': 'twitter',
        'display_name': 'Twitter',
        'install': 'pip install python-twitter',
        'login_handler': 'flask.ext.social::TwitterLoginHandler',
        'connect_handler': 'flask.ext.social::TwitterConnectHandler',
        'connection_factory': 'flask.ext.social::TwitterConnectionFactory',
        'oauth': {
            'base_url': 'http://api.twitter.com/1/',
            'request_token_url': 'https://api.twitter.com/oauth/request_token',
            'access_token_url': 'https://api.twitter.com/oauth/access_token',
            'authorize_url': 'https://api.twitter.com/oauth/authenticate',
        },
    },
    'facebook': {
        'id': 'facebook',
        'display_name': 'Facebook',
        'install': 'pip install http://github.com/pythonforfacebook/facebook-sdk/tarball/master',
        'login_handler': 'flask.ext.social::FacebookLoginHandler',
        'connect_handler': 'flask.ext.social::FacebookConnectHandler',
        'connection_factory': 'flask.ext.social::FacebookConnectionFactory',
        'oauth': {
            'base_url': 'https://graph.facebook.com/',
            'request_token_url': None,
            'access_token_url': '/oauth/access_token',
            'authorize_url': 'https://www.facebook.com/dialog/oauth',
        },
    },
    'google': {
        'id': 'google',
        'display_name': 'Google',
        'install': 'pip install google-api-python-client',
        'login_handler': 'flask.ext.social::GoogleLoginHandler',
        'connect_handler': 'flask.ext.social::GoogleConnectHandler',
        'connection_factory': 'flask.ext.social::GoogleConnectionFactory',
        'oauth': {
            'base_url': 'https://www.google.com/accounts/',
            'authorize_url': 'https://accounts.google.com/o/oauth2/auth',
            'access_token_url': 'https://accounts.google.com/o/oauth2/token',
            'access_token_method': 'POST',
            'access_token_params': {
                'grant_type': 'authorization_code'
            },
            'request_token_url': None,
            'request_token_params': {
                'response_type': 'code'
            },
        }
    },
    'foursquare': {
        'id': 'foursquare',
        'display_name': 'foursquare',
        'install': 'pip install foursquare',
        'login_handler': 'flask.ext.social::FoursquareLoginHandler',
        'connect_handler': 'flask.ext.social::FoursquareConnectHandler',
        'connection_factory': 'flask.ext.social::FoursquareConnectionFactory',
        'oauth': {
            'base_url': 'https://api.foursquare.com/v2/',
            'request_token_url': None,
            'access_token_url': 'https://foursquare.com/oauth2/access_token',
            'authorize_url': 'https://foursquare.com/oauth2/authenticate',
            'access_token_params': {
                'grant_type': 'authorization_code'
            },
            'request_token_params': {
                'response_type': 'code'
            },
        }
    }
}


class FacebookConnectionFactory(ConnectionFactory):
    """The `FacebookConnectionFactory` class creates `Connection` instances for
    accounts connected to Facebook. The API instance for Facebook connections
    are instances of the `Facebook Python libary <https://github.com/pythonforfacebook/facebook-sdk>`_.
    """
    def __init__(self, **kwargs):
        super(FacebookConnectionFactory, self).__init__('facebook')

    def _create_api(self, connection):
        return facebook.GraphAPI(getattr(connection, 'access_token'))


class TwitterConnectionFactory(ConnectionFactory):
    """The `TwitterConnectionFactory` class creates `Connection` instances for
    accounts connected to Twitter. The API instance for Twitter connections
    are instances of the `python-twitter library <http://code.google.com/p/python-twitter/>`_
    """
    def __init__(self, consumer_key, consumer_secret, **kwargs):
        super(TwitterConnectionFactory, self).__init__('twitter')
        self.consumer_key = consumer_key
        self.consumer_secret = consumer_secret

    def _create_api(self, connection):
        return twitter.Api(consumer_key=self.consumer_key,
                           consumer_secret=self.consumer_secret,
                           access_token_key=getattr(connection, 'access_token'),
                           access_token_secret=getattr(connection, 'secret'))


class GoogleConnectionFactory(ConnectionFactory):
    """The `GoogleConnectionFactory` class creates `Connection` instances for
    accounts connected to google. The API instance for google connections
    are instances of the `google library <http://code.google.com/p/google-api-python-client/>`_
    """
    def __init__(self, consumer_key, consumer_secret, **kwargs):
        super(GoogleConnectionFactory, self).__init__('google')
        self.consumer_key = consumer_key
        self.consumer_secret = consumer_secret

    def _create_api(self, connection):
        credentials = googleoauth.AccessTokenCredentials(
            access_token=getattr(connection, 'access_token'),
            user_agent=''
        )

        http = httplib2.Http()
        http = credentials.authorize(http)
        return googleapi.build('plus', 'v1', http=http)


class FoursquareConnectionFactory(ConnectionFactory):
    """The `FoursquareConnectionFactory` class creates `Connection` instances for
    accounts connected to foursquare. The API instance for foursquare connections
    are instances of the `foursquare library <https://github.com/mLewisLogic/foursquare/>`_
    """
    def __init__(self, consumer_key, consumer_secret, **kwargs):
        super(FoursquareConnectionFactory, self).__init__('foursquare')
        self.consumer_key = consumer_key
        self.consumer_secret = consumer_secret

    def _create_api(self, connection):
        return foursquare.Foursquare(
                access_token=getattr(connection, 'access_token'))


class TwitterLoginHandler(LoginHandler):
    """The `TwitterLoginHandler` class handles the authorization response from
    Twitter. The Twitter account's user ID is passed with the authorization
    response and an extra API call is not necessary.
    """
    def __init__(self, **kwargs):
        super(TwitterLoginHandler, self).__init__('twitter',
                                                  kwargs.get('callback'))

    def get_provider_user_id(self, response):
        return response['user_id'] if response else None


class FacebookLoginHandler(LoginHandler):
    """The `FacebookLoginHandler` class handles the authorization response from
    Facebook. The Facebook account's user ID is not passed in the response,
    thus it must be retrieved with an API call.
    """
    def __init__(self, **kwargs):
        super(FacebookLoginHandler, self).__init__('facebook',
                                                  kwargs.get('callback'))

    def get_provider_user_id(self, response):
        if response:
            graph = facebook.GraphAPI(response['access_token'])
            profile = graph.get_object("me")
            return profile['id']
        return None


class GoogleLoginHandler(LoginHandler):
    """The `GoogleLoginHandler` class handles the authorization response from
    google. The google account's user ID is not passed in the response,
    thus it must be retrieved with an API call.
    """
    def __init__(self, **kwargs):
        super(GoogleLoginHandler, self).__init__('google',
                                                  kwargs.get('callback'))

    def get_provider_user_id(self, response):
        if response:
            credentials = googleoauth.AccessTokenCredentials(
                access_token=response['access_token'],
                user_agent=''
            )

            http = httplib2.Http()
            http = credentials.authorize(http)
            api = googleapi.build('plus', 'v1', http=http)
            profile = api.people().get(userId='me').execute()
            return profile['id']
        return None


class FoursquareLoginHandler(LoginHandler):
    """The `FoursquareLoginHandler` class handles the authorization response from
    foursquare. The foursquare account's user ID is not passed in the response,
    thus it must be retrieved with an API call.
    """
    def __init__(self, **kwargs):
        super(FoursquareLoginHandler, self).__init__('foursquare',
                                                  kwargs.get('callback'))

    def get_provider_user_id(self, response):
        if response:
            api = foursquare.Foursquare(
                access_token=getattr(response, 'access_token'))
            return api.users()['user']['id']
        return None


class TwitterConnectHandler(ConnectHandler):
    """The `TwitterConnectHandler` class handles the connection procedure
    after a user authorizes a connection from Twitter. The connection values
    are all retrieved from the response, no extra API calls are necessary.
    """
    def __init__(self, **kwargs):
        super(TwitterConnectHandler, self).__init__('twitter',
                                                    kwargs.get('callback'))
        self.consumer_key = kwargs['consumer_key']
        self.consumer_secret = kwargs['consumer_secret']

    def get_connection_values(self, response=None):
        if not response:
            return None

        api = twitter.Api(consumer_key=self.consumer_key,
                          consumer_secret=self.consumer_secret,
                          access_token_key=response['oauth_token'],
                          access_token_secret=response['oauth_token_secret'])

        user = api.VerifyCredentials()

        return dict(
            provider_id=self.provider_id,
            provider_user_id=str(user.id),
            access_token=response['oauth_token'],
            secret=response['oauth_token_secret'],
            display_name='@%s' % user.screen_name,
            profile_url="http://twitter.com/%s" % user.screen_name,
            image_url=user.profile_image_url
        )


class FacebookConnectHandler(ConnectHandler):
    """The `FacebookConnectHandler` class handles the connection procedure
    after a user authorizes a connection from Facebook. The Facebook acount's
    user ID is retrieved via an API call, otherwise the token is provided by
    the response from Facebook.
    """
    def __init__(self, **kwargs):
        super(FacebookConnectHandler, self).__init__('facebook',
                                                     kwargs.get('callback'))

    def get_connection_values(self, response):
        if not response:
            return None

        access_token = response['access_token']
        graph = facebook.GraphAPI(access_token)
        profile = graph.get_object("me")
        profile_url = "http://facebook.com/profile.php?id=%s" % profile['id']
        image_url = "http://graph.facebook.com/%s/picture" % profile['id']

        return dict(
            provider_id=self.provider_id,
            provider_user_id=profile['id'],
            access_token=access_token,
            secret=None,
            display_name=profile['username'],
            profile_url=profile_url,
            image_url=image_url
        )


class GoogleConnectHandler(ConnectHandler):
    """The `GoogleConnectHandler` class handles the connection procedure
    after a user authorizes a connection from google. The google acount's
    user ID is retrieved via an API call, otherwise the token is provided by
    the response from google.
    """
    def __init__(self, **kwargs):
        super(GoogleConnectHandler, self).__init__('google',
                                                   kwargs.get('callback'))

    def get_connection_values(self, response):
        if not response:
            return None

        access_token = response['access_token']

        credentials = googleoauth.AccessTokenCredentials(
            access_token=access_token,
            user_agent=''
        )

        http = httplib2.Http()
        http = credentials.authorize(http)
        api = googleapi.build('plus', 'v1', http=http)
        profile = api.people().get(userId='me').execute()

        return dict(
            provider_id=self.provider_id,
            provider_user_id=profile['id'],
            access_token=access_token,
            secret=None,
            display_name=profile['displayName'],
            profile_url=profile['url'],
            image_url=profile['image']['url']
        )


class FoursquareConnectHandler(ConnectHandler):
    """The `FoursquareConnectHandler` class handles the connection procedure
    after a user authorizes a connection from foursquare. The foursquare acount's
    user ID is retrieved via an API call, otherwise the token is provided by
    the response from foursquare.
    """
    def __init__(self, **kwargs):
        super(FoursquareConnectHandler, self).__init__('foursquare',
                                                       kwargs.get('callback'))

    def get_connection_values(self, response):
        if not response:
            return None

        access_token = response['access_token']
        api = foursquare.Foursquare(access_token=access_token)
        user = api.users()['user']
        profile_url = user['canonicalUrl']
        image_url = user['photo']

        return dict(
            provider_id=self.provider_id,
            provider_user_id=user['id'],
            access_token=access_token,
            secret=None,
            display_name=profile_url.split('/')[-1:][0],
            profile_url=profile_url,
            image_url=image_url
        )


class Social(object):
    """The `Social` extension adds integration with various service providers to
    your application. Currently Twitter and Facebook are supported. When
    properly configured, Social will add endpoints to your app that allows for
    users to connect their accounts with a service provider and eventually
    login via these accounts as well.

    To start the process of connecting a service provider account with a local
    user account perform an HTTP POST to /connect/<provider_id>. This endpoint
    requires that the user be logged in already. This will initiate the OAuth
    flow with the provider. If the user authorizes access the provider should
    perform an HTTP GET on the same URL. Social will then attempt to store a
    connection to the account using the response values. Once the connection is
    made you can retrieve a `Connection` instance for the current user via::

        from flask import current_app
        connection = current_app.social.<provider_id>.get_connection()
        connection.api.some_api_method()

    Replace <provider_id> with the provider you wish to get a connection to.
    The above example also illustrates a hypothetical API call. A connection
    includes a configured instance of the provider's API and you can perform
    any API calls the connection's OAuth token allows.

    To start the process of a logging in a user through their provider account,
    perform an HTTP POST to /login/<provider_id>. This will initiate the OAuth
    flow with the provider. If the user authorizes access or has already
    authorized access the provider should perform an HTTP GET on the previously
    mentioned URL. Social will attempt to handle the login by checking if a
    connection between the provider account and a local user account. If one
    exists the user is automatically logged in. If a connection does not exist
    the user is redirected to the login view specified by the Auth module.

    Additionally, other endpoints are included to help manage connections.

    Delete all connections for the logged in user to a provider:

        [DELETE] /connect/<provider_id>

    Delete a specific connection to a service provider for the logged in user:

        [DELETE] /connect/<provider_id>/<provider_user_id>
    """
    def __init__(self, app=None, datastore=None):
        self.providers = {}
        self.init_app(app, datastore)

    def init_app(self, app, datastore):
        """Initialize the application with the Social module

        :param app: The Flask application
        :param datastore: Connection datastore instance
        """
        app.social = self
        self.datastore = datastore

        for key, value in default_config.items():
            app.config.setdefault(key, value)

        # get service provider configurations
        provider_configs = []

        for provider, provider_config in default_provider_config.items():
            provider_key = 'SOCIAL_%s' % provider.upper()

            if provider_key in app.config:
                d_config = provider_config.copy()

                try:
                    __import__(d_config['id'])
                except ImportError:
                    app.logger.error(
                        'Could not import %s API module. Please install via:\n'
                        '%s' % (d_config['display_name'], d_config['install']))

                d_oauth_config = d_config['oauth'].copy()

                d_config.update(app.config[provider_key])
                d_oauth_config.update(app.config[provider_key]['oauth'])
                d_config['oauth'] = d_oauth_config

                app.config[provider_key] = d_config
                provider_configs.append(d_config)

        self.oauth = OAuth()

        # Configure the URL handlers for each fo the configured providers
        url_prefix = config_value('URL_PREFIX', app=app)
        blueprint = views.create_blueprint(app, 'flask_social', __name__,
                                           url_prefix=url_prefix)

        for pc in provider_configs:
            views.configure_provider(app, blueprint, self.oauth, pc)

        app.register_blueprint(blueprint)

    def register_provider(self, name, provider):
        self.providers[name] = provider

    def __getattr__(self, name):
        return self.providers.get(name, None)

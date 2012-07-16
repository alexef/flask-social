
from flask import Blueprint, current_app, redirect, request, session
from flask.ext.security import current_user, login_required, login_user
from flask.ext.security.utils import get_post_login_redirect

from flask_social import exceptions
from flask_social.core import Provider
from flask_social.signals import social_connection_removed, \
     social_connection_created, social_connection_failed, \
     social_login_completed, social_login_failed
from flask_social.utils import do_flash, config_value, get_display_name, \
     get_authorize_callback, get_remote_app, get_class_from_string


def configure_provider(app, blueprint, oauth, config):
    """
    Configures and registers a service provider connection Factory with the
    main application. The connection factory is accessible via:

        from flask import current_app as app
        app.social.<provider_id>
    """
    provider_id = config['id']
    o_config = config['oauth']

    try:
        o_config['consumer_key']
        o_config['consumer_secret']
    except KeyError:
        raise Exception('consumer_key and/or consumer_secret not found '
                        'for provider %s' % config['display_name'])

    remote_app = oauth.remote_app(provider_id, **o_config)

    def get_handler(clazz_name, config, callback):
        return get_class_from_string(clazz_name)(callback=callback, **config)

    cf_class_name = config['connection_factory']
    ConnectionFactoryClass = get_class_from_string(cf_class_name)

    cf = ConnectionFactoryClass(**o_config)
    lh = get_handler(config['login_handler'], o_config, login_handler)
    ch = get_handler(config['connect_handler'], o_config, connect_handler)

    service_provider = Provider(remote_app, cf, lh, ch)

    @service_provider.tokengetter
    def get_token():
        # Social doesn't use the builtin remote method calls feature of the
        # Flask-OAuth extension so we don't need to return a token. This does,
        # however, need to be configured
        return None

    @blueprint.route('/connect/%s' % provider_id, methods=['GET'],
                     endpoint='connect_%s_callback' % provider_id)
    @login_required
    @service_provider.authorized_handler
    def connect_callback(response):
        """The route which the provider should redirect to after a user
        attempts to connect their account with the provider with their local
        application account
        """
        return getattr(app.social, provider_id).connect_handler(response)

    @blueprint.route('/login/%s' % provider_id, methods=['GET'],
                     endpoint='login_%s_callback' % provider_id)
    @service_provider.authorized_handler
    def login_callback(response):
        """The route which the provider should redirect to after a user
        attempts to login with their account with the provider
        """
        return getattr(app.social, provider_id).login_handler(response)

    app.social.register_provider(provider_id, service_provider)
    app.logger.debug('Registered social provider: %s' % service_provider)


def login(provider_id):
    """Starts the provider login OAuth flow"""
    if current_user.is_authenticated():
        return redirect(request.referrer or '/')

    callback_url = get_authorize_callback('/login/%s' % provider_id)
    display_name = get_display_name(provider_id)

    current_app.logger.debug('Starting login via %s account. Callback '
        'URL = %s' % (display_name, callback_url))

    post_login = request.form.get('next', get_post_login_redirect())
    session['post_oauth_login_url'] = post_login

    return get_remote_app(provider_id).authorize(callback_url)


def login_handler(provider_id, provider_user_id, oauth_response):
    """Shared method to handle the signin process"""

    if current_user.is_authenticated():
        return redirect("/")

    display_name = get_display_name(provider_id)

    current_app.logger.debug('Attempting login via %s with provider user '
                     '%s' % (display_name, provider_user_id))
    try:
        connection = current_app.social.datastore \
            .get_connection_by_provider_user_id(provider_id, provider_user_id)
        user = current_app.security.datastore.with_id(connection.user_id)

        if login_user(user):
            key = config_value('POST_OAUTH_LOGIN_SESSION_KEY')
            redirect_url = session.pop(key, get_post_login_redirect())

            current_app.logger.debug('User logged in via %s. Redirecting to '
                                     '%s' % (display_name, redirect_url))
            social_login_completed.send(current_app._get_current_object(),
                                        provider_id=provider_id, user=user)
            return redirect(redirect_url)

        else:
            current_app.logger.info('Inactive local user attempted '
                                    'login via %s.' % display_name)
            do_flash("Inactive user", "error")

    except exceptions.ConnectionNotFoundError:
        current_app.logger.info('Login attempt via %s failed because '
                                'connection was not found.' % display_name)

        msg = '%s account not associated with an existing user' % display_name
        do_flash(msg, 'error')

    except Exception, e:
        current_app.logger.error('Unexpected error signing in '
                                 'via %s: %s' % (display_name, e))

    social_login_failed.send(current_app._get_current_object(),
                             provider_id=provider_id,
                             oauth_response=oauth_response)

    return redirect(current_app.security.login_manager.login_view)


def connect(provider_id):
    """Starts the provider connection OAuth flow"""
    callback_url = get_authorize_callback('/connect/%s' % provider_id)

    ctx = dict(display_name=get_display_name(provider_id),
               current_user=current_user,
               callback_url=callback_url)

    current_app.logger.debug('Starting process of connecting '
        '%(display_name)s account to user account %(current_user)s. '
        'Callback URL = %(callback_url)s' % ctx)

    allow_view = config_value('CONNECT_ALLOW_REDIRECT')
    pc = request.form.get('next', allow_view)
    session[config_value('POST_OAUTH_CONNECT_SESSION_KEY')] = pc

    return get_remote_app(provider_id).authorize(callback_url)


def connect_handler(cv, user_id=None):
    """Shared method to handle the connection process

    :param connection_values: A dictionary containing the connection values
    :param provider_id: The provider ID the connection shoudl be made to
    """
    provider_id = cv['provider_id']
    display_name = get_display_name(provider_id)
    cv['user_id'] = user_id or current_user.get_id()

    try:
        connection = current_app.social.datastore.save_connection(**cv)
        current_app.logger.debug('Connection to %s established '
                                 'for %s' % (display_name, current_user))
        social_connection_created.send(current_app._get_current_object(),
                                       user=current_user._get_current_object(),
                                       connection=connection)
        do_flash("Connection established to %s" % display_name, 'success')

    except exceptions.ConnectionExistsError, e:
        current_app.logger.debug('Connection to %s exists already '
                                 'for %s' % (display_name, current_user))
        do_flash("A connection is already established with %s "
              "to your account" % display_name, 'notice')

    except Exception, e:
        current_app.logger.error('Unexpected error connecting %s account for '
                                 'user. Reason: %s' % (display_name, e))
        social_connection_failed.send(current_app._get_current_object(),
                                      user=current_user._get_current_object(),
                                      error=e)
        do_flash("Could not make connection to %s. "
              "Please try again later." % display_name, 'error')

    redirect_url = session.pop(config_value('POST_OAUTH_CONNECT_SESSION_KEY'),
                               config_value('CONNECT_ALLOW_REDIRECT'))
    return redirect(redirect_url)


def remove_all_connections(provider_id):
    """Remove all connections for the authenticated user to the
    specified provider
    """
    display_name = get_display_name(provider_id)
    ctx = dict(provider=display_name, user=current_user)

    try:
        current_app.social.datastore.remove_all_connections(
            current_user.get_id(), provider_id)

        social_connection_removed.send(
            current_app._get_current_object(),
            user=current_user._get_current_object(),
            provider_id=provider_id)

        current_app.logger.debug('Removed all connections to '
                                 '%(provider)s for %(user)s' % ctx)

        do_flash("All connections to %s removed" % display_name, 'info')
    except:
        current_app.logger.error('Unable to remove all connections to '
                                 '%(provider)s for %(user)s' % ctx)

        msg = "Unable to remove connection to %(provider)s" % ctx
        do_flash(msg, 'error')

    return redirect(request.referrer)


def remove_connection(provider_id, provider_user_id):
    """Remove a specific connection for the authenticated user to the
    specified provider
    """
    display_name = get_display_name(provider_id)
    ctx = dict(provider=display_name,
               user=current_user,
               provider_user_id=provider_user_id)

    try:
        current_app.social.datastore.remove_connection(
            current_user.get_id(),
            provider_id,
            provider_user_id)

        social_connection_removed.send(
            current_app._get_current_object(),
            user=current_user._get_current_object(),
            provider_id=provider_id)

        current_app.logger.debug('Removed connection to %(provider)s '
            'account %(provider_user_id)s for %(user)s' % ctx)

        do_flash("Connection to %(provider)s removed" % ctx, 'info')

    except exceptions.ConnectionNotFoundError:
        current_app.logger.error(
            'Unable to remove connection to %(provider)s account '
            '%(provider_user_id)s for %(user)s' % ctx)

        do_flash("Unabled to remove connection to %(provider)s" % ctx,
              'error')

    return redirect(request.referrer)


def create_blueprint(app, name, import_name, **kwargs):
    bp = Blueprint(name, import_name, **kwargs)

    bp.route('/login/<provider_id>',
             methods=['POST'])(login)

    bp.route('/connect/<provider_id>',
             methods=['POST'])(login_required(connect))

    bp.route('/connect/<provider_id>',
             methods=['DELETE'])(login_required(remove_all_connections))

    bp.route('/connect/<provider_id>/<provider_user_id>',
             methods=['DELETE'])(login_required(remove_connection))

    return bp

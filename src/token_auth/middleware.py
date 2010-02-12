import datetime

from django.conf import settings
from django.http import HttpResponseRedirect
from django.core.urlresolvers import reverse
from django.contrib.auth.models import AnonymousUser, User
from django.contrib.auth import login, get_backends

from token_auth.models import ProtectedURL, ProtectedURLToken
from token_auth.signals import token_visited


class ProtectedURLsMiddleware(object):
    def check_for_user_or_token(self, request, protected):
        """
        Function that checks if user is authenticated or token cookie exists
        """
        if not isinstance(request.user, AnonymousUser) and request.user.is_authenticated():
            return True
        if getattr(request, 'protectedurltoken', None):
            return True
        return False
    
    def token_expired(self, token):
        if token.valid_until and not token.valid_until >= datetime.datetime.now(): return False
        else: return True
    
    def process_request(self, request):
        tokens = request.COOKIES.get('protectedurltokens', '')            
        tokens_list = tokens and tokens.split('|') or []
        tokens = ProtectedURLToken.active_objects.filter(token__in=tokens_list).order_by('url__url').select_related('url')
        if tokens:
            for token in tokens:
                if request.path.startswith(token.url.url):
                    token_visited.send(sender=self.__class__, request=request, token=token)
            request.protectedurltoken = token[0]
            return
        request.protectedurltoken = None
            
    def process_response(self, request, response):
        is_protected = False
        # the following does a ``startswith`` on the DB records without pulling all the objects first
        where_sql = 'substr(%s, 0, length(url)) = url'
        if ProtectedURL.active_objects.extra(where=[where_sql], params=[request.path]):
            is_protected = True
        if is_protected:
            has_permission = self.check_for_user_or_token(request)
            if not has_permission:
                return HttpResponseRedirect(reverse('protectedurl_protected') + "?url=" + request.path)
        return response


class TokenAuthLoginMiddleware(object):
    def process_request(self, request):
        token = getattr(request, 'protectedurltoken', None)
        if token:
            if isinstance(request.user, AnonymousUser):
                try:
                    user = User.objects.get(email=token.email)
                except User.DoesNotExist:
                    user = None
                if user:
                    backend = get_backends()[0]
                    user.backend = "%s.%s" % (backend.__module__, backend.__class__.__name__)
                    login(request, user)

#!/usr/bin/env python

from __future__ import print_function

import base64
import string
from argparse import ArgumentParser
from io import open
from os import environ, path, makedirs
from zlib import compress

import httplib2
import six
from six.moves.urllib.parse import urlencode

if six.PY2:
    from string import maketrans
else:
    maketrans = bytes.maketrans

__version__ = 0, 3, 0
__version_string__ = '.'.join(str(x) for x in __version__)

__author__ = 'Doug Napoleone, Samuel Marks, Eric Frederich'
__email__ = 'doug.napoleone+plantuml@gmail.com'


plantuml_alphabet = string.digits + string.ascii_uppercase + string.ascii_lowercase + '-_'
base64_alphabet   = string.ascii_uppercase + string.ascii_lowercase + string.digits + '+/'
b64_to_plantuml = maketrans(base64_alphabet.encode('utf-8'), plantuml_alphabet.encode('utf-8'))


class PlantUMLError(Exception):
    """
    Error in processing.
    """
    pass


class PlantUMLConnectionError(PlantUMLError):
    """
    Error connecting or talking to PlantUML Server.
    """
    pass


class PlantUMLHTTPError(PlantUMLConnectionError):
    """
    Request to PlantUML server returned HTTP Error.
    """

    def __init__(self, response, content, *args, **kwdargs):
        super(PlantUMLConnectionError, self).__init__(*args, **kwdargs)
        self.response = response
        self.content = content
        if not self.message:
            self.message = "%d: %s" % (
                self.response.status, self.response.reason)


def deflate_and_encode(plantuml_text):
    """zlib compress the plantuml text and encode it for the plantuml server.
    """
    zlibbed_str = compress(plantuml_text.encode('utf-8'))
    compressed_string = zlibbed_str[2:-4]
    return base64.b64encode(compressed_string).translate(b64_to_plantuml).decode('utf-8')


class PlantUML(object):
    """Connection to a PlantUML server with optional authentication.
    
    All parameters are optional.
    
    :param str url: URL to the PlantUML server image CGI. defaults to
                    http://www.plantuml.com/plantuml/img/
    :param dict basic_auth: This is if the plantuml server requires basic HTTP
                    authentication. Dictionary containing two keys, 'username'
                    and 'password', set to appropriate values for basic HTTP
                    authentication.
    :param dict form_auth: This is for plantuml server requires a cookie based
                    webform login authentication. Dictionary containing two
                    primary keys, 'url' and 'body'. The 'url' should point to
                    the login URL for the server, and the 'body' should be a
                    dictionary set to the form elements required for login.
                    The key 'method' will default to 'POST'. The key 'headers'
                    defaults to
                    {'Content-type':'application/x-www-form-urlencoded'}.
                    Example: form_auth={'url': 'http://example.com/login/',
                    'body': { 'username': 'me', 'password': 'secret'}
    :param dict http_opts: Extra options to be passed off to the
                    httplib2.Http() constructor.
    :param dict request_opts: Extra options to be passed off to the
                    httplib2.Http().request() call.
                    
    """

    def __init__(self, url, basic_auth={}, form_auth={},
                 http_opts={}, request_opts={}):
        self.HttpLib2Error = httplib2.HttpLib2Error
        self.url = url
        self.request_opts = request_opts
        self.auth_type = 'basic_auth' if basic_auth else (
            'form_auth' if form_auth else None)
        self.auth = basic_auth if basic_auth else (
            form_auth if form_auth else None)

        # Proxify
        try:
            from urlparse import urlparse
            import socks

            proxy_uri = urlparse(environ.get('HTTPS_PROXY', environ.get('HTTP_PROXY')))
            if proxy_uri:
                proxy = {'proxy_info': httplib2.ProxyInfo(socks.PROXY_TYPE_HTTP,
                                                          proxy_uri.hostname, proxy_uri.port)}
                http_opts.update(proxy)
                self.request_opts.update(proxy)
        except ImportError:
            pass

        self.http = httplib2.Http(**http_opts)

        if self.auth_type == 'basic_auth':
            self.http.add_credentials(
                self.auth['username'], self.auth['password'])
        elif self.auth_type == 'form_auth':
            if 'url' not in self.auth:
                raise PlantUMLError(
                    "The form_auth option 'url' must be provided and point to "
                    "the login url.")
            if 'body' not in self.auth:
                raise PlantUMLError(
                    "The form_auth option 'body' must be provided and include "
                    "a dictionary with the form elements required to log in. "
                    "Example: form_auth={'url': 'http://example.com/login/', "
                    "'body': { 'username': 'me', 'password': 'secret'}")
            login_url = self.auth['url']
            body = self.auth['body']
            method = self.auth.get('method', 'POST')
            headers = self.auth.get(
                'headers', {'Content-type': 'application/x-www-form-urlencoded'})
            try:
                response, content = self.http.request(
                    login_url, method, headers=headers,
                    body=urlencode(body))
            except self.HttpLib2Error as e:
                raise PlantUMLConnectionError(e)
            if response.status != 200:
                raise PlantUMLHTTPError(response, content)
            self.request_opts['Cookie'] = response['set-cookie']

    def get_url(self, plantuml_text):
        """Return the server URL for the image.
        You can use this URL in an IMG HTML tag.
        
        :param str plantuml_text: The plantuml markup to render
        :returns: the plantuml server image URL
        """
        return self.url + deflate_and_encode(plantuml_text)

    def processes(self, plantuml_text):
        """Processes the plantuml text into the raw PNG image data.
        
        :param str plantuml_text: The plantuml markup to render
        :returns: the raw image data
        """
        url = self.get_url(plantuml_text)
        try:
            response, content = self.http.request(url, **self.request_opts)
        except self.HttpLib2Error as e:
            raise PlantUMLConnectionError(e)
        if response.status != 200:
            raise PlantUMLHTTPError(response, content)
        return content

    def processes_file(self, filename, outfile=None, errorfile=None, directory=''):
        """Take a filename of a file containing plantuml text and processes
        it into a .png image.
        
        :param str filename: Text file containing plantuml markup
        :param str outfile: Filename to write the output image to. If not
                    supplied, then it will be the input filename with the
                    file extension replaced with '.png'.
        :param str errorfile: Filename to write server html error page
                    to. If this is not supplined, then it will be the
                    input ``filename`` with the extension replaced with
                    '_error.html'.
        :returns: ``True`` if the image write succedded, ``False`` if there was
                    an error written to ``errorfile``.
        """
        if outfile is None:
            outfile = path.splitext(filename)[0] + '.png'
        if errorfile is None:
            errorfile = path.splitext(filename)[0] + '_error.html'
        if directory and not path.exists(directory):
            makedirs(directory)
        data = open(filename).read()
        try:
            content = self.processes(data)
        except PlantUMLHTTPError as e:
            err = open(path.join(directory, errorfile), 'w')
            err.write(e.content)
            err.close()
            return False
        out = open(path.join(directory, outfile), 'wb')
        out.write(content)
        out.close()
        return True


def _build_parser():
    parser = ArgumentParser(description='Generate images from plantuml defined files using plantuml server')
    parser.add_argument('files', metavar='filename', nargs='+',
                        help='file(s) to generate images from')
    parser.add_argument('-o', '--out', default='',
                        help='directory to put the files into')
    parser.add_argument('-s', '--server', default='http://www.plantuml.com/plantuml/img/',
                        help='server to generate from, defaults to "http://www.plantuml.com/plantuml/img/"')
    return parser


def main():
    args = _build_parser().parse_args()
    pl = PlantUML(args.server)
    print(list(map(lambda filename: {'filename': filename,
                                'gen_success': pl.processes_file(filename, directory=args.out)}, args.files)))


if __name__ == '__main__':
    main()

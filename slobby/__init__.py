import argparse
import functools
import json
import os
import urllib

from itertools import islice

import cherrypy

from slob import open as slopen, find, UTF8


KEY_VALUE_ROW = '<tr><td style="vertical-align: top">{0}</td><td>{1}</td></tr>'
LI_VALUE = '<li>{}</li>'
WORD_LI = '<li><a href="{0}" title="From {2}" target="content">{1}</a></li>'

HTML = '''
<html>
  <body>
{0}
  </body>
</html>
'''

NOTHING_FOUND = ('<div align="center"><em>'
                 'Nothing found for <strong>{0}</strong></em></div>')

TPATH = os.path.join(os.path.dirname(__file__), 'slobby.html')
with open(TPATH) as f:
    TEMPLATE = f.read()

CSSPATH = os.path.join(os.path.dirname(__file__), 'slobby.css')
with open(CSSPATH) as f:
    CSS = f.read()

URL = functools.partial(cherrypy.url, relative='server')

class Root:

    exposed = True

    def __init__(self, names, limit):
        self.slobs = {}
        for name in names:
            slob = slopen(name)
            self.slobs[slob.id] = slob

        self.lookup = Lookup(self.slobs, limit)
        self.slob = Content(self.slobs)
        self.dictionaries = Dictionaries(self.slobs)

    def GET(self):
        raise cherrypy.HTTPRedirect(URL('/lookup'))


class Dictionaries:

    exposed = True

    def __init__(self, slobs):
        self.slobs = slobs


    def GET(self):
        html = []

        for slob in self.slobs.values():
            title = slob.tags.get('label', slob.id)
            html.append('<h1>{0}</h1>'.format(title))
            html.append('<table>')
            html.append(KEY_VALUE_ROW.format('id', slob.id))
            html.append(KEY_VALUE_ROW.format('encoding', slob.encoding))
            html.append(KEY_VALUE_ROW.format('compression', slob.compression))
            html.append(KEY_VALUE_ROW.format('key count', len(slob)))
            html.append(KEY_VALUE_ROW.format('blob count', slob.blob_count))

            content_types_list = ['<ul>']
            for content_type in slob.content_types:
                content_types_list.append(LI_VALUE.format(content_type))
            content_types_list.append('</ul>')
            html.append(KEY_VALUE_ROW.format('content types',
                                             ''.join(content_types_list)))
            tags_table = ['<table>']
            for k, v in sorted(slob.tags.items()):
                tags_table.append(KEY_VALUE_ROW.format(k, v))
            tags_table.append('</table>')
            html.append(KEY_VALUE_ROW.format('tags', ''.join(tags_table)))
            html.append('</table>')
        cherrypy.response.headers['Content-Type'] = 'text/html;charset:utf-8'
        return HTML.format(''.join(html)).encode('utf-8')


class Lookup:

    exposed = True

    def __init__(self, slobs, limit):
        self.slobs = slobs
        self.limit = limit

    def GET(self, *args, word=None, limit=None):
        if limit is None:
            limit = self.limit
        content_url = None
        if word or args:
            limit = int(limit)
            if word is None:
                #wsgi weirdness
                word = args[0].encode('ISO-8859-1').decode(UTF8)
            result = []
            lookup_result = find(word, self.slobs.values())
            for slob, item in islice(lookup_result, limit):
                result.append((slob.id, item))
            html = []
            if not result:
                html.append(NOTHING_FOUND.format(word))
            else:
                html.append('<ul>')
                for slob_id, item in result:
                    href = mk_content_link(slob_id, item)
                    if content_url is None:
                        content_url = href
                    html.append(WORD_LI.format(
                        href, item.key,
                        self.slobs[slob_id].tags.get('label', slob_id)))
                html.append('</ul>')
        else:
            html = []
        if content_url is None:
            content_url = 'about:blank'
        ret = TEMPLATE.format(style=CSS,
                              word=word or '',
                              wordlist=''.join(html),
                              content_url=content_url)
        cherrypy.response.headers['Content-Type'] = 'text/html;charset:utf-8'
        return ret.encode('utf-8')


class Content:

    exposed = True

    def __init__(self, slobs):
        self.slobs = slobs

    def to_info(self, s):
        return {
            'id': s.id,
            'compression': s.compression,
            'encoding': s.encoding,
            'blobCount': s.blob_count,
            'refCount': len(s),
            'contentTypes': s.content_types,
            'tags': dict(s.tags)
        }

    def find_slob(self, id_or_uri):
        slob = self.slobs.get(id_or_uri)
        if slob:
            return slob, True
        for slob in self.slobs.values():
            uri = slob.tags.get('uri')
            if uri and id_or_uri == uri:
                return slob, False

    def GET(self, *args, key=None, blob=None, **_kwargs):
        print(args, key, blob)
        if len(args) == 0:
            cherrypy.response.headers['Content-Type'] = 'application/json'
            data = [self.to_info(s) for s in self.slobs.values()]
            return json.dumps(data, indent=2).encode('utf8')
        if len(args) == 1:
            slob_id_or_uri = args[0]
            slob, _ = self.find_slob(slob_id_or_uri)
            if slob:
                cherrypy.response.headers['Content-Type'] = 'application/json'
                cherrypy.response.headers['Cache-Control'] = 'no-cache'
                return json.dumps(self.to_info(slob), indent=2).encode('utf8')
            else:
                raise cherrypy.NotFound

        blob_id = blob

        if len(args) >= 2:
            key = '/'.join(args[1:])

        slob_id_or_uri = args[0]
        if_none_match = cherrypy.request.headers.get("If-None-Match")
        slob, is_slob_id = self.find_slob(slob_id_or_uri)

        if not slob:
            raise cherrypy.NotFound

        if is_slob_id and blob_id:
            content_type, content = slob.get(int(blob_id))
            cherrypy.response.headers['Content-Type'] = content_type
            cherrypy.response.headers['Cache-Control'] = 'max-age=31556926'
            return content

        if key and if_none_match:
            e_tag = '"{}"'.format(slob.id)
            if if_none_match == e_tag:
                cherrypy.response.status = 304
                return

        #wsgi weirdness
        key = key.encode('ISO-8859-1').decode('utf8')

        print ('Key:', repr(key))
        print ('Slob:', slob)

        for slob, item in find(key, slob, match_prefix=False):
            if is_slob_id:
                cherrypy.response.headers['Cache-Control'] = 'max-age=31556926'
            else:
                cherrypy.response.headers['Cache-Control'] = 'max-age=600'
                e_tag = '"{}"'.format(slob.id)
                cherrypy.response.headers['ETag'] = e_tag
            cherrypy.response.headers['Content-Type'] = item.content_type

            return item.content

        cherrypy.response.status = 404
        return NOTHING_FOUND.format(key if key else blob).encode('utf-8')


def mk_content_link(slob_id, item):
    href = '/slob/{slob_id}/{key}?blob={blob_id}#{fragment}'.format(
        slob_id=slob_id,
        key=item.key,
        blob_id=item.id,
        fragment=item.fragment)
    return URL(href)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('slob', nargs='+',
                        help=('Slob file name (or base name if '
                              'opening slob split into multiple files)'))
    parser.add_argument('-p', '--port', type=int, default=8013,
                        help=('Port for web server to listen on. '
                              'Default: %(default)s'))
    parser.add_argument('-i', '--interface', default='127.0.0.1',
                        help=('Network interface for web server to listen on. '
                              'Default: %(default)s'))
    parser.add_argument('-t', '--threads', type=int, default=6,
                        help=('Number of threads in web server\'s thread pool. '
                              'Default: %(default)s'))
    parser.add_argument('-l', '--limit', type=int, default=100,
                        help=('Maximum number of keys lookup may return. '
                              'Default: %(default)s'))
    parser.add_argument('-b', '--browse', action='store_true',
                        help='Open web browser and load lookup page')
    parser.add_argument('-m', '--mount-path', type=str, default='/',
                        help=('Website root. This facilitates setting up '
                              'access through a reverse proxy like nginx '
                              'Default: %(default)s'))

    args = parser.parse_args()

    cherrypy.config.update( {
        'server.socket_port': args.port,
        'server.thread_pool': args.threads,
        'server.socket_host': args.interface,
        'tools.encode.on': False
    })

    if args.browse:
        import webbrowser
        def open_browser():
            if args.interface == '0.0.0.0':
                host = 'localhost'
            else:
                host = args.interface
            webbrowser.open('http://{0}:{1}/'.format(host, args.port))
        cherrypy.engine.subscribe('start', open_browser)

    config = {'/': {'request.dispatch': cherrypy.dispatch.MethodDispatcher()}}
    cherrypy.quickstart(Root(args.slob, args.limit),
                        args.mount_path, config=config)

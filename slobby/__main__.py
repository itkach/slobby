import argparse
import os
import urllib
import functools

from string import Template

from itertools import islice

import cherrypy

from slob import open_, find, UTF8


KEY_VALUE_ROW = '<tr><td style="vertical-align: top">{0}</td><td>{1}</td></tr>'

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
    TEMPLATE = Template(f.read())


URL = functools.partial(cherrypy.url, relative='server')

class Root:

    exposed = True

    def __init__(self, names, limit):
        self.slobs = {}
        for name in names:
            slob = open_(name)
            self.slobs[slob.id] = slob

        self.lookup = Lookup(self.slobs, limit)
        self.content = Content(self.slobs)
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
            html.append(KEY_VALUE_ROW.format('key count', len(slob)))
            html.append(KEY_VALUE_ROW.format('blob count', slob.blob_count))
            tags_table = ['<table>']
            for k, v in sorted(slob.tags.items()):
                tags_table.append(KEY_VALUE_ROW.format(k, v))
            tags_table.append('</table>')
            html.append(KEY_VALUE_ROW.format('tags', ''.join(tags_table)))
            html.append('</table>')
        return HTML.format(''.join(html))


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
        ret = TEMPLATE.substitute(word=word or '',
                                  wordlist=''.join(html),
                                  content_url=content_url)
        return ret


class Content:

    exposed = True

    def __init__(self, slobs):
        self.slobs = slobs

    def GET(self, word=None, _id=None):
        if _id:
            slob_id, blob_id = _id.split('-')
            if slob_id not in self.slobs:
                raise cherrypy.NotFound
            content_type, content = self.slobs[slob_id].get(int(blob_id))
            cherrypy.response.headers['Content-Type'] = content_type
            return content
        elif word:
            #wsgi weirdness
            word = word.encode('ISO-8859-1').decode('utf8')
            try:
                referer = cherrypy.request.headers.get('Referer')
                if referer:
                    p = urllib.parse.urlparse(referer)
                    q = urllib.parse.parse_qs(p.query)
                    if '_id' in q:
                        preferred_id = q['_id'][0].split('-', 1)[0]
                        if preferred_id in self.slobs:
                            try:
                                slob, item = next(find(word,
                                                       self.slobs[preferred_id],
                                                       match_prefix=False))
                            except StopIteration:
                                pass
                            else:
                                direct_to(slob, item)
                slob, item = next(find(word, self.slobs.values(),
                                       match_prefix=False))
                # Redirect instead of returning content like directly so that
                # referer header always contains slob id to look there first
                # when folloing links
                ## cherrypy.response.headers['Content-Type'] = item.content_type
                ## return item.content
                direct_to(slob, item)
            except StopIteration:
                pass
        return NOTHING_FOUND.format(word if word else _id)


def mk_content_link(slob_id, item):
    href = '/content/?_id={slob_id}-{content_id}#{fragment}'.format(
        slob_id=slob_id,
        content_id=item.id,
        fragment=item.fragment)
    return URL(href)

def direct_to(slob, item):
    raise cherrypy.HTTPRedirect(mk_content_link(slob.id, item))


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
        'tools.encode.on': True
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


main()

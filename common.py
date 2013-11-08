__author__ = 'tho'

import platform
import os
import subprocess
import sys
import time
import re

from config import conf, gnuplot_cmd

GNUPLOT_COMMON = 'set terminal png transparent size 640,240\nset size 1.0,1.0\n'
ON_LINUX = (platform.system() == 'Linux')
WEEKDAYS = ('Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun')
exectime_internal = 0.0
exectime_external = 0.0

def html_linkify(text):
    return text.lower().replace(' ', '_')

def html_header(level, text):
    name = html_linkify(text)
    return '\n<h%d><a href="#%s" name="%s">%s</a></h%d>\n\n' % (level, name, name, text, level)

def getkeyssortedbyvalues(dict):
    return map(lambda el : el[1], sorted(map(lambda el : (el[1], el[0]), dict.items())))

def getpipeoutput(cmds, quiet = False):
    global exectime_external
    start = time.time()
    if not quiet and ON_LINUX and os.isatty(1):
        print('>> ' + ' | '.join(cmds))
        sys.stdout.flush()
    p0 = subprocess.Popen(cmds[0], stdout = subprocess.PIPE, shell = True)
    p = p0
    for x in cmds[1:]:
        p = subprocess.Popen(x, stdin = p0.stdout, stdout = subprocess.PIPE, shell = True)
        p0 = p
    output = p.communicate()[0]
    end = time.time()
    if not quiet:
        if ON_LINUX and os.isatty(1):
            print('\r')
        print('[%.5f] >> %s' % (end - start, ' | '.join(cmds)))
    exectime_external += (end - start)
    return output.rstrip('\n')

def getversion():
    global VERSION
    if VERSION == 0:
        gitstats_repo = os.path.dirname(os.path.abspath(__file__))
        VERSION = getpipeoutput(["git --git-dir=%s/.git --work-tree=%s rev-parse --short %s %s" %
            (gitstats_repo, gitstats_repo, getcommitrange('HEAD').split('\n')[0], get_commit_time())])
    return VERSION

def getgitversion():
    return getpipeoutput(['git --version']).split('\n')[0]

def getgnuplotversion():
    return getpipeoutput(['%s --version' % gnuplot_cmd]).split('\n')[0]

def getnumoffilesfromrev(time_rev):
    """
    Get number of files changed in commit
    """
    time, rev = time_rev
    return (int(time), rev, int(getpipeoutput(['git ls-tree -r --name-only "%s"' % rev, 'wc -l']).split('\n')[0]))

def getnumoflinesinblob(ext_blob):
    """
    Get number of lines in blob
    """
    ext, blob_id = ext_blob
    return (ext, blob_id, int(getpipeoutput(['git cat-file blob %s' % blob_id, 'wc -l']).split()[0]))


def getcommitrange(defaultrange = 'HEAD', end_only = False):
    if len(conf['commit_end']) > 0:
        if end_only or len(conf['commit_begin']) == 0:
            return conf['commit_end']
        return '%s..%s' % (conf['commit_begin'], conf['commit_end'])
    return defaultrange

def get_commit_time():
    timerange = ""
    if len(conf['time_end']) > 0:
        timerange += ('--before="%s"' % conf['time_end'])
    if len(conf['time_begin']) > 0:
        timerange += ('--since="%s"' % conf['time_begin'])

    return timerange


# dict['author'] = { 'commits': 512 } - ...key(dict, 'commits')
def getkeyssortedbyvaluekey(d, key):
    return map(lambda el : el[1], sorted(map(lambda el : (d[el][key], el), d.keys())))

def getstatsummarycounts(line):
    numbers = re.findall('\d+', line)
    if   len(numbers) == 1:
        # neither insertions nor deletions: may probably only happen for "0 files changed"
        numbers.append(0);
        numbers.append(0);
    elif len(numbers) == 2 and line.find('(+)') != -1:
        numbers.append(0);    # only insertions were printed on line
    elif len(numbers) == 2 and line.find('(-)') != -1:
        numbers.insert(1, 0); # only deletions were printed on line
    return numbers

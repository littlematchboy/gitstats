#!/usr/bin/env python
# Copyright (c) 2007-2013 Heikki Hokkanen <hoxu@users.sf.net> & others (see doc/author.txt)
# GPLv2 / GPLv3
from datetime import datetime
import getopt
import os
import sys
import time
from common import *
from GitDataCollector import GitDataCollector

from HtmlReportCreator import HTMLReportCreator
from common import getgnuplotversion, exectime_external
from config import conf

if sys.version_info < (2, 6):
    print >> sys.stderr, "Python 2.6 or higher is required for gitstats"
    sys.exit(1)

os.environ['LC_ALL'] = 'C'
time_start = time.time()


def usage():
    print("""
Usage: gitstats [options] <gitpath..> <outputpath>

Options:
-c key=value     Override configuration value

Default config values:
%s

Please see the manual page for more details.
""" % conf)


class GitStats:
    def run(self, args_orig):
        optlist, args = getopt.getopt(args_orig, 'hc:', ["help"])
        for o, v in optlist:
            if o == '-c':
                key, value = v.split('=', 1)
                if key not in conf:
                    raise KeyError('no such key "%s" in config' % key)
                if isinstance(conf[key], int):
                    conf[key] = int(value)
                elif isinstance(conf[key], dict):
                    kk, vv = value.split(',', 1)
                    conf[key][kk] = vv
                else:
                    conf[key] = value
            elif o in ('-h', '--help'):
                usage()
                sys.exit()

        if len(args) < 1:
            usage()
            sys.exit(0)

        rundir = os.getcwd()

        # if output is not specified, output to web directory (default folder)
        if len(args) == 1:
            outputpath = conf['output']
        else:
            outputpath = os.path.abspath(args[-1])

        try:
            os.makedirs(outputpath)
        except OSError:
            pass
        if not os.path.isdir(outputpath):
            print('FATAL: Output path is not a directory or does not exist')
            sys.exit(1)

        if not getgnuplotversion():
            print('gnuplot not found')
            sys.exit(1)

        print('Output path: %s' % outputpath)
        cachefile = os.path.join(outputpath, 'gitstats.cache')

        if len(args) == 1:
            gitpaths = args[0:]
        else:
            gitpaths = args[0:-1]

        gitpath = gitpaths[0]
        # only for 1 path
        # for gitpath in gitpaths:

        print('Git path: %s' % gitpath)

        main_branch = 'master'
        lines = getpipeoutput(['git branch -a']).split('\n')
        for line in lines:
            data = GitDataCollector()
            data.loadCache(cachefile)

            if len(line) < 2:
                continue
            line = line[2:]
            branch_name = line.split(' ')[0].replace('remotes/origin/', '')
            if branch_name == 'HEAD':
                main_branch = line.split(' ')[2]
                continue

            os.chdir(gitpath)

            print('Collecting data...')
            data.collect(gitpath)
            os.chdir(rundir)

            print('Refining data...')
            data.saveCache(cachefile)
            data.refine()

            os.chdir(rundir)

            print('Generating report...')

            output_suffix = conf['output_suffix']
            single_project_output_path = os.path.join(outputpath, data.projectname, output_suffix)

            time_begin = conf['time_begin']
            time_end = conf['time_end']
            if not time_end:
                time_end = datetime.now().strftime("%Y-%m-%d")
            if time_begin:
                # time_format = '%Y-%m-%d %H:%M:%S'
                single_project_output_path = os.path.join(single_project_output_path, "%s to %s" % (time_begin, time_end))
            else:
                single_project_output_path = os.path.join(single_project_output_path, "all")

            try:
                os.makedirs(single_project_output_path)
            except OSError:
                pass
            if not os.path.isdir(single_project_output_path):
                print('FATAL: Unable to create output folder')
                sys.exit(1)

            report = HTMLReportCreator()
            report.create(data, single_project_output_path, branch_name)

        time_end = time.time()
        exectime_internal = time_end - time_start
        print('Execution time %.5f secs, %.5f secs (%.2f %%) in external commands)' % (
        exectime_internal, exectime_external, (100.0 * exectime_external) / exectime_internal))
        if sys.stdin.isatty():
            print('Finished!')


if __name__ == '__main__':
    g = GitStats()
    g.run(sys.argv[1:])


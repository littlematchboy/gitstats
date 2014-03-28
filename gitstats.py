#!/usr/bin/env python
# Copyright (c) 2007-2013 Heikki Hokkanen <hoxu@users.sf.net> & others (see doc/author.txt)
# GPLv2 / GPLv3
from datetime import datetime
import getopt
from common import *
from GitDataCollector import GitDataCollector

from HtmlReportCreator import HTMLReportCreator
from common import getgnuplotversion, exectime_external
from config import conf

if sys.version_info < (2, 6):
    print("Python 2.6 or higher is required for GitStats")
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
            output_path = conf['output']
        else:
            output_path = os.path.abspath(args[-1])

        try:
            os.makedirs(output_path)
        except OSError:
            pass
        if not os.path.isdir(output_path):
            print('FATAL: Output path is not a directory or does not exist')
            sys.exit(1)

        if not getgnuplotversion():
            print('gnuplot not found')
            sys.exit(1)

        print('Output path: %s' % output_path)
        cached_file = os.path.join(output_path, 'gitstats.cache')

        if len(args) == 1:
            input_paths = args[0:]
        else:
            input_paths = args[0:-1]

        input_path = input_paths[0]
        # only for 1 path
        # for gitpath in gitpaths:

        print('Git path: %s' % input_path)
        print('Running dir: %s' % rundir)
        project_dir = os.path.basename(os.path.abspath(input_path))

        # loop through all branches, generate report for each branch
        main_branch = 'master'
        lines = getpipeoutput(['git branch -a']).split('\n')
        for line in lines:
            data = GitDataCollector()

            # get local branch name
            if len(line) < 2:
                continue
            line = line[2:]
            branch_name = line.split(' ')[0].replace('remotes/origin/', '')
            if branch_name == 'HEAD':
                main_branch = line.split(' ')[2]
                continue

            os.chdir(rundir)

            getpipeoutput(['git branch %s --track origin/%s' % (branch_name, branch_name)])
            getpipeoutput(['git checkout %s' % branch_name])
            getpipeoutput(['git merge FETCH_HEAD'])

            print('Collecting data...')
            data.collect(input_path)
            os.chdir(rundir)

            print('Refining data...')
            data.saveCache(cached_file)
            data.refine()

            os.chdir(rundir)

            print('project dir: %s' % project_dir)
            print('Generating report...')
            print('Output dir: %s' % output_path)

            output_suffix = conf['output_suffix']
            single_project_output_path = os.path.join(output_path, data.projectname, output_suffix)

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

        print("Switch back to main branch: %s" % main_branch)
        getpipeoutput(['git checkout %s' % main_branch])

        time_end = time.time()
        exectime_internal = time_end - time_start
        print('Execution time %.5f secs, %.5f secs (%.2f %%) in external commands)' % (
        exectime_internal, exectime_external, (100.0 * exectime_external) / exectime_internal))
        if sys.stdin.isatty():
            print('Finished!')


if __name__ == '__main__':
    g = GitStats()
    g.run(sys.argv[1:])


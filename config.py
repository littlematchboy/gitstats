__author__ = 'tho'

import os

conf = {
    'max_domains': 10,
    'max_ext_length': 10,
    'style': 'gitstats.css',
    'max_authors': 20,
    'authors_top': 5,
    'commit_begin': '',
    'commit_end': 'HEAD',
    'time_begin': '',
    'time_end': '',
    'linear_linestats': 1,
    'project_name': '',
    'merge_authors': {},
    'output': '/opt/web/gitstats/',
    'processes': 8,
}

# By default, gnuplot is searched from path, but can be overridden with the
# environment variable "GNUPLOT"
gnuplot_cmd = 'gnuplot'
if 'GNUPLOT' in os.environ:
    gnuplot_cmd = os.environ['GNUPLOT']
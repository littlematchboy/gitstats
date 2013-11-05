#!/usr/bin/env python
# Copyright (c) 2007-2013 Heikki Hokkanen <hoxu@users.sf.net> & others (see doc/author.txt)
# GPLv2 / GPLv3
import datetime
import getopt
import glob
import os
import pickle
import platform
import re
import shutil
import subprocess
import sys
import time
import zlib

if sys.version_info < (2, 6):
       print >> sys.stderr, "Python 2.6 or higher is required for gitstats"
       sys.exit(1)

from multiprocessing import Pool

os.environ['LC_ALL'] = 'C'

GNUPLOT_COMMON = 'set terminal png transparent size 640,240\nset size 1.0,1.0\n'
ON_LINUX = (platform.system() == 'Linux')
WEEKDAYS = ('Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun')

exectime_internal = 0.0
exectime_external = 0.0
time_start = time.time()

# By default, gnuplot is searched from path, but can be overridden with the
# environment variable "GNUPLOT"
gnuplot_cmd = 'gnuplot'
if 'GNUPLOT' in os.environ:
    gnuplot_cmd = os.environ['GNUPLOT']

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

def getpipeoutput(cmds, quiet = False):
    global exectime_external
    start = time.time()
    if not quiet and ON_LINUX and os.isatty(1):
        print '>> ' + ' | '.join(cmds),
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
            print '\r',
        print '[%.5f] >> %s' % (end - start, ' | '.join(cmds))
    exectime_external += (end - start)
    return output.rstrip('\n')

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

def getkeyssortedbyvalues(dict):
    return map(lambda el : el[1], sorted(map(lambda el : (el[1], el[0]), dict.items())))

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

VERSION = 0
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

class DataCollector:
    """Manages data collection from a revision control repository."""
    def __init__(self):
        self.stamp_created = time.time()
        self.cache = {}
        self.total_authors = 0
        self.activity_by_hour_of_day = {} # hour -> commits
        self.activity_by_day_of_week = {} # day -> commits
        self.activity_by_month_of_year = {} # month [1-12] -> commits
        self.activity_by_hour_of_week = {} # weekday -> hour -> commits
        self.activity_by_hour_of_day_busiest = 0
        self.activity_by_hour_of_week_busiest = 0
        self.activity_by_year_week = {} # yy_wNN -> commits
        self.activity_by_year_week_peak = 0

        self.authors = {} # name -> {commits, first_commit_stamp, last_commit_stamp, last_active_day, active_days, lines_added, lines_removed}

        self.total_commits = 0
        self.total_files = 0
        self.authors_by_commits = 0

        # domains
        self.domains = {} # domain -> commits

        # author of the month
        self.author_of_month = {} # month -> author -> commits
        self.author_of_year = {} # year -> author -> commits
        self.commits_by_month = {} # month -> commits
        self.commits_by_year = {} # year -> commits
        self.lines_added_by_month = {} # month -> lines added
        self.lines_added_by_year = {} # year -> lines added
        self.lines_removed_by_month = {} # month -> lines removed
        self.lines_removed_by_year = {} # year -> lines removed
        self.first_commit_stamp = 0
        self.last_commit_stamp = 0
        self.last_active_day = None
        self.active_days = set()

        # lines
        self.total_lines = 0
        self.total_lines_added = 0
        self.total_lines_removed = 0

        # size
        self.total_size = 0

        # timezone
        self.commits_by_timezone = {} # timezone -> commits

        # tags
        self.tags = {}

        self.files_by_stamp = {} # stamp -> files

        # extensions
        self.extensions = {} # extension -> files, lines

        # line statistics
        self.changes_by_date = {} # stamp -> { files, ins, del }

    ##
    # This should be the main function to extract data from the repository.
    def collect(self, dir):
        self.dir = dir
        if len(conf['project_name']) == 0:
            self.projectname = os.path.basename(os.path.abspath(dir))
        else:
            self.projectname = conf['project_name']
    
    ##
    # Load cacheable data
    def loadCache(self, cachefile):
        if not os.path.exists(cachefile):
            return
        print 'Loading cache...'
        f = open(cachefile, 'rb')
        try:
            self.cache = pickle.loads(zlib.decompress(f.read()))
        except:
            # temporary hack to upgrade non-compressed caches
            f.seek(0)
            self.cache = pickle.load(f)
        f.close()
    
    ##
    # Produce any additional statistics from the extracted data.
    def refine(self):
        pass

    ##
    # : get a dictionary of author
    def getAuthorInfo(self, author):
        return None
    
    def getActivityByDayOfWeek(self):
        return {}

    def getActivityByHourOfDay(self):
        return {}

    # : get a dictionary of domains
    def getDomainInfo(self, domain):
        return None

    ##
    # Get a list of authors
    def getAuthors(self):
        return []
    
    def getFirstCommitDate(self):
        return datetime.datetime.now()
    
    def getLastCommitDate(self):
        return datetime.datetime.now()
    
    def getStampCreated(self):
        return self.stamp_created
    
    def getTags(self):
        return []
    
    def getTotalAuthors(self):
        return -1
    
    def getTotalCommits(self):
        return -1
        
    def getTotalFiles(self):
        return -1
    
    def getTotalLOC(self):
        return -1
    
    ##
    # Save cacheable data
    def saveCache(self, cachefile):
        print 'Saving cache...'
        tempfile = cachefile + '.tmp'
        f = open(tempfile, 'wb')
        #pickle.dump(self.cache, f)
        data = zlib.compress(pickle.dumps(self.cache))
        f.write(data)
        f.close()
        try:
            os.remove(cachefile)
        except OSError:
            pass
        os.rename(tempfile, cachefile)

class GitDataCollector(DataCollector):
    def collect(self, dir):
        DataCollector.collect(self, dir)

        self.total_authors += int(getpipeoutput(['git shortlog -s %s %s' % (getcommitrange(), get_commit_time()), 'wc -l']))
        #self.total_lines = int(getoutput('git-ls-files -z |xargs -0 cat |wc -l'))

        # tags
        lines = getpipeoutput(['git show-ref --tags']).split('\n')
        for line in lines:
            if len(line) == 0:
                continue
            (hash, tag) = line.split(' ')

            tag = tag.replace('refs/tags/', '')
            output = getpipeoutput(['git log "%s" --pretty=format:"%%at %%aN" -n 1' % hash])
            if len(output) > 0:
                parts = output.split(' ')
                stamp = 0
                try:
                    stamp = int(parts[0])
                except ValueError:
                    stamp = 0
                self.tags[tag] = { 'stamp': stamp, 'hash' : hash, 'date' : datetime.datetime.fromtimestamp(stamp).strftime('%Y-%m-%d'), 'commits': 0, 'authors': {} }

        # collect info on tags, starting from latest
        tags_sorted_by_date_desc = map(lambda el : el[1], reversed(sorted(map(lambda el : (el[1]['date'], el[0]), self.tags.items()))))
        prev = None
        for tag in reversed(tags_sorted_by_date_desc):
            cmd = 'git shortlog -s "%s"' % tag
            if prev != None:
                cmd += ' "^%s"' % prev
            output = getpipeoutput([cmd])
            if len(output) == 0:
                continue
            prev = tag
            for line in output.split('\n'):
                parts = re.split('\s+', line, 2)
                commits = int(parts[1])
                author = parts[2]
                if author in conf['merge_authors']:
                    author = conf['merge_authors'][author]
                self.tags[tag]['commits'] += commits
                self.tags[tag]['authors'][author] = commits

        # Collect revision statistics
        # Outputs "<stamp> <date> <time> <timezone> <author> '<' <mail> '>'"
        rev_list_output = getpipeoutput(['git rev-list --pretty=format:"%%at %%ai %%aN <%%aE>" %s %s' % (getcommitrange('HEAD'), get_commit_time()), 'grep -v ^commit'])
        if rev_list_output:
            lines = rev_list_output.split('\n')
        else:
            lines = []
        for line in lines:
            parts = line.split(' ', 4)
            author = ''
            try:
                stamp = int(parts[0])
            except ValueError:
                stamp = 0
            timezone = parts[3]
            author, mail = parts[4].split('<', 1)
            author = author.rstrip()
            if author in conf['merge_authors']:
                author = conf['merge_authors'][author]
            mail = mail.rstrip('>')
            domain = '?'
            if mail.find('@') != -1:
                domain = mail.rsplit('@', 1)[1]
            date = datetime.datetime.fromtimestamp(float(stamp))

            # First and last commit stamp (may be in any order because of cherry-picking and patches)
            if stamp > self.last_commit_stamp:
                self.last_commit_stamp = stamp
            if self.first_commit_stamp == 0 or stamp < self.first_commit_stamp:
                self.first_commit_stamp = stamp

            # activity
            # hour
            hour = date.hour
            self.activity_by_hour_of_day[hour] = self.activity_by_hour_of_day.get(hour, 0) + 1
            # most active hour?
            if self.activity_by_hour_of_day[hour] > self.activity_by_hour_of_day_busiest:
                self.activity_by_hour_of_day_busiest = self.activity_by_hour_of_day[hour]

            # day of week
            day = date.weekday()
            self.activity_by_day_of_week[day] = self.activity_by_day_of_week.get(day, 0) + 1

            # domain stats
            if domain not in self.domains:
                self.domains[domain] = {}
            # commits
            self.domains[domain]['commits'] = self.domains[domain].get('commits', 0) + 1

            # hour of week
            if day not in self.activity_by_hour_of_week:
                self.activity_by_hour_of_week[day] = {}
            self.activity_by_hour_of_week[day][hour] = self.activity_by_hour_of_week[day].get(hour, 0) + 1
            # most active hour?
            if self.activity_by_hour_of_week[day][hour] > self.activity_by_hour_of_week_busiest:
                self.activity_by_hour_of_week_busiest = self.activity_by_hour_of_week[day][hour]

            # month of year
            month = date.month
            self.activity_by_month_of_year[month] = self.activity_by_month_of_year.get(month, 0) + 1

            # yearly/weekly activity
            yyw = date.strftime('%Y-%W')
            self.activity_by_year_week[yyw] = self.activity_by_year_week.get(yyw, 0) + 1
            if self.activity_by_year_week_peak < self.activity_by_year_week[yyw]:
                self.activity_by_year_week_peak = self.activity_by_year_week[yyw]

            # author stats
            if author not in self.authors:
                self.authors[author] = {}
            # commits, note again that commits may be in any date order because of cherry-picking and patches
            if 'last_commit_stamp' not in self.authors[author]:
                self.authors[author]['last_commit_stamp'] = stamp
            if stamp > self.authors[author]['last_commit_stamp']:
                self.authors[author]['last_commit_stamp'] = stamp
            if 'first_commit_stamp' not in self.authors[author]:
                self.authors[author]['first_commit_stamp'] = stamp
            if stamp < self.authors[author]['first_commit_stamp']:
                self.authors[author]['first_commit_stamp'] = stamp

            # author of the month/year
            yymm = date.strftime('%Y-%m')
            if yymm in self.author_of_month:
                self.author_of_month[yymm][author] = self.author_of_month[yymm].get(author, 0) + 1
            else:
                self.author_of_month[yymm] = {}
                self.author_of_month[yymm][author] = 1
            self.commits_by_month[yymm] = self.commits_by_month.get(yymm, 0) + 1

            yy = date.year
            if yy in self.author_of_year:
                self.author_of_year[yy][author] = self.author_of_year[yy].get(author, 0) + 1
            else:
                self.author_of_year[yy] = {}
                self.author_of_year[yy][author] = 1
            self.commits_by_year[yy] = self.commits_by_year.get(yy, 0) + 1

            # authors: active days
            yymmdd = date.strftime('%Y-%m-%d')
            if 'last_active_day' not in self.authors[author]:
                self.authors[author]['last_active_day'] = yymmdd
                self.authors[author]['active_days'] = set([yymmdd])
            elif yymmdd != self.authors[author]['last_active_day']:
                self.authors[author]['last_active_day'] = yymmdd
                self.authors[author]['active_days'].add(yymmdd)

            # project: active days
            if yymmdd != self.last_active_day:
                self.last_active_day = yymmdd
                self.active_days.add(yymmdd)

            # timezone
            self.commits_by_timezone[timezone] = self.commits_by_timezone.get(timezone, 0) + 1

        # outputs "<stamp> <files>" for each revision
        revlines = getpipeoutput(['git rev-list --pretty=format:"%%at %%T" %s %s' % (getcommitrange('HEAD'), get_commit_time()), 'grep -v ^commit']).strip().split('\n')
        lines = []
        revs_to_read = []
        time_rev_count = []
        #Look up rev in cache and take info from cache if found
        #If not append rev to list of rev to read from repo
        for revline in revlines:
            if not (' ' in revline):
                continue
            time, rev = revline.split(' ')
            #if cache empty then add time and rev to list of new rev's
            #otherwise try to read needed info from cache
            if 'files_in_tree' not in self.cache.keys():
                revs_to_read.append((time,rev))
                continue
            if rev in self.cache['files_in_tree'].keys():
                lines.append('%d %d' % (int(time), self.cache['files_in_tree'][rev]))
            else:
                revs_to_read.append((time,rev))

        #Read revisions from repo
        time_rev_count = Pool(processes=conf['processes']).map(getnumoffilesfromrev, revs_to_read)

        #Update cache with new revisions and append then to general list
        for (time, rev, count) in time_rev_count:
            if 'files_in_tree' not in self.cache:
                self.cache['files_in_tree'] = {}
            self.cache['files_in_tree'][rev] = count
            lines.append('%d %d' % (int(time), count))

        self.total_commits += len(lines)
        for line in lines:
            parts = line.split(' ')
            if len(parts) != 2:
                continue
            (stamp, files) = parts[0:2]
            try:
                self.files_by_stamp[int(stamp)] = int(files)
            except ValueError:
                print 'Warning: failed to parse line "%s"' % line

        # extensions and size of files
        lines = getpipeoutput(['git ls-tree -r -l -z %s %s' % (getcommitrange('HEAD', end_only = True), get_commit_time()) ]).split('\000')
        blobs_to_read = []
        for line in lines:
            if len(line) == 0:
                continue
            parts = re.split('\s+', line, 5)
            if parts[0] == '160000' and parts[3] == '-':
                # skip submodules
                continue
            blob_id = parts[2]
            size = int(parts[3])
            fullpath = parts[4]

            self.total_size += size
            self.total_files += 1

            filename = fullpath.split('/')[-1] # strip directories
            if filename.find('.') == -1 or filename.rfind('.') == 0:
                ext = ''
            else:
                ext = filename[(filename.rfind('.') + 1):]
            if len(ext) > conf['max_ext_length']:
                ext = ''
            if ext not in self.extensions:
                self.extensions[ext] = {'files': 0, 'lines': 0}
            self.extensions[ext]['files'] += 1
            #if cache empty then add ext and blob id to list of new blob's
            #otherwise try to read needed info from cache
            if 'lines_in_blob' not in self.cache.keys():
                blobs_to_read.append((ext,blob_id))
                continue
            if blob_id in self.cache['lines_in_blob'].keys():
                self.extensions[ext]['lines'] += self.cache['lines_in_blob'][blob_id]
            else:
                blobs_to_read.append((ext,blob_id))

        #Get info abount line count for new blob's that wasn't found in cache
        ext_blob_linecount = Pool(processes=24).map(getnumoflinesinblob, blobs_to_read)

        #Update cache and write down info about number of number of lines
        for (ext, blob_id, linecount) in ext_blob_linecount:
            if 'lines_in_blob' not in self.cache:
                self.cache['lines_in_blob'] = {}
            self.cache['lines_in_blob'][blob_id] = linecount
            self.extensions[ext]['lines'] += self.cache['lines_in_blob'][blob_id]

        # line statistics
        # outputs:
        #  N files changed, N insertions (+), N deletions(-)
        # <stamp> <author>
        self.changes_by_date = {} # stamp -> { files, ins, del }
        # computation of lines of code by date is better done
        # on a linear history.
        extra = ''
        if conf['linear_linestats']:
            extra = '--first-parent -m'
        lines = getpipeoutput(['git log --shortstat %s --pretty=format:"%%at %%aN" %s %s' % (extra, getcommitrange('HEAD'), get_commit_time())]).split('\n')
        lines.reverse()
        files = 0; inserted = 0; deleted = 0; total_lines = 0
        author = None
        for line in lines:
            if len(line) == 0:
                continue

            # <stamp> <author>
            if re.search('files? changed', line) == None:
                pos = line.find(' ')
                if pos != -1:
                    try:
                        (stamp, author) = (int(line[:pos]), line[pos+1:])
                        if author in conf['merge_authors']:
                            author = conf['merge_authors'][author]
                        self.changes_by_date[stamp] = { 'files': files, 'ins': inserted, 'del': deleted, 'lines': total_lines }

                        date = datetime.datetime.fromtimestamp(stamp)
                        yymm = date.strftime('%Y-%m')
                        self.lines_added_by_month[yymm] = self.lines_added_by_month.get(yymm, 0) + inserted
                        self.lines_removed_by_month[yymm] = self.lines_removed_by_month.get(yymm, 0) + deleted

                        yy = date.year
                        self.lines_added_by_year[yy] = self.lines_added_by_year.get(yy,0) + inserted
                        self.lines_removed_by_year[yy] = self.lines_removed_by_year.get(yy, 0) + deleted

                        files, inserted, deleted = 0, 0, 0
                    except ValueError:
                        print 'Warning: unexpected line "%s"' % line
                else:
                    print 'Warning: unexpected line "%s"' % line
            else:
                numbers = getstatsummarycounts(line)

                if len(numbers) == 3:
                    (files, inserted, deleted) = map(lambda el : int(el), numbers)
                    total_lines += inserted
                    total_lines -= deleted
                    self.total_lines_added += inserted
                    self.total_lines_removed += deleted

                else:
                    print 'Warning: failed to handle line "%s"' % line
                    (files, inserted, deleted) = (0, 0, 0)
                #self.changes_by_date[stamp] = { 'files': files, 'ins': inserted, 'del': deleted }
        self.total_lines += total_lines

        # Per-author statistics

        # defined for stamp, author only if author commited at this timestamp.
        self.changes_by_date_by_author = {} # stamp -> author -> lines_added

        # Similar to the above, but never use --first-parent
        # (we need to walk through every commit to know who
        # committed what, not just through mainline)
        lines = getpipeoutput(['git log --shortstat --date-order --pretty=format:"%%at %%aN" %s %s' % (getcommitrange('HEAD'), get_commit_time())]).split('\n')
        lines.reverse()
        files = 0; inserted = 0; deleted = 0
        author = None
        stamp = 0
        for line in lines:
            if len(line) == 0:
                continue

            # <stamp> <author>
            if re.search('files? changed', line) == None:
                pos = line.find(' ')
                if pos != -1:
                    try:
                        oldstamp = stamp
                        (stamp, author) = (int(line[:pos]), line[pos+1:])
                        if author in conf['merge_authors']:
                            author = conf['merge_authors'][author]
                        if oldstamp > stamp:
                            # clock skew, keep old timestamp to avoid having ugly graph
                            stamp = oldstamp
                        if author not in self.authors:
                            self.authors[author] = { 'lines_added' : 0, 'lines_removed' : 0, 'commits' : 0}
                        self.authors[author]['commits'] = self.authors[author].get('commits', 0) + 1
                        self.authors[author]['lines_added'] = self.authors[author].get('lines_added', 0) + inserted
                        self.authors[author]['lines_removed'] = self.authors[author].get('lines_removed', 0) + deleted
                        if stamp not in self.changes_by_date_by_author:
                            self.changes_by_date_by_author[stamp] = {}
                        if author not in self.changes_by_date_by_author[stamp]:
                            self.changes_by_date_by_author[stamp][author] = {}
                        self.changes_by_date_by_author[stamp][author]['lines_added'] = self.authors[author]['lines_added']
                        self.changes_by_date_by_author[stamp][author]['commits'] = self.authors[author]['commits']
                        files, inserted, deleted = 0, 0, 0
                    except ValueError:
                        print 'Warning: unexpected line "%s"' % line
                else:
                    print 'Warning: unexpected line "%s"' % line
            else:
                numbers = getstatsummarycounts(line);

                if len(numbers) == 3:
                    (files, inserted, deleted) = map(lambda el : int(el), numbers)
                else:
                    print 'Warning: failed to handle line "%s"' % line
                    (files, inserted, deleted) = (0, 0, 0)
    
    def refine(self):
        # authors
        # name -> {place_by_commits, commits_frac, date_first, date_last, timedelta}
        self.authors_by_commits = getkeyssortedbyvaluekey(self.authors, 'commits')
        self.authors_by_commits.reverse() # most first
        for i, name in enumerate(self.authors_by_commits):
            self.authors[name]['place_by_commits'] = i + 1

        for name in self.authors.keys():
            a = self.authors[name]
            a['commits_frac'] = (100 * float(a['commits'])) / self.getTotalCommits()
            date_first = datetime.datetime.fromtimestamp(a['first_commit_stamp'])
            date_last = datetime.datetime.fromtimestamp(a['last_commit_stamp'])
            delta = date_last - date_first
            a['date_first'] = date_first.strftime('%Y-%m-%d')
            a['date_last'] = date_last.strftime('%Y-%m-%d')
            a['timedelta'] = delta
            if 'lines_added' not in a: a['lines_added'] = 0
            if 'lines_removed' not in a: a['lines_removed'] = 0
    
    def getActiveDays(self):
        return self.active_days

    def getActivityByDayOfWeek(self):
        return self.activity_by_day_of_week

    def getActivityByHourOfDay(self):
        return self.activity_by_hour_of_day

    def getAuthorInfo(self, author):
        return self.authors[author]
    
    def getAuthors(self, limit = None):
        res = getkeyssortedbyvaluekey(self.authors, 'commits')
        res.reverse()
        return res[:limit]
    
    def getCommitDeltaDays(self):
        return (self.last_commit_stamp / 86400 - self.first_commit_stamp / 86400) + 1

    def getDomainInfo(self, domain):
        return self.domains[domain]

    def getDomains(self):
        return self.domains.keys()
    
    def getFirstCommitDate(self):
        return datetime.datetime.fromtimestamp(self.first_commit_stamp)
    
    def getLastCommitDate(self):
        return datetime.datetime.fromtimestamp(self.last_commit_stamp)
    
    def getTags(self):
        lines = getpipeoutput(['git show-ref --tags', 'cut -d/ -f3'])
        return lines.split('\n')
    
    def getTagDate(self, tag):
        return self.revToDate('tags/' + tag)
    
    def getTotalAuthors(self):
        return self.total_authors
    
    def getTotalCommits(self):
        return self.total_commits

    def getTotalFiles(self):
        return self.total_files
    
    def getTotalLOC(self):
        return self.total_lines

    def getTotalSize(self):
        return self.total_size
    
    def revToDate(self, rev):
        stamp = int(getpipeoutput(['git log --pretty=format:%%at "%s" -n 1' % rev]))
        return datetime.datetime.fromtimestamp(stamp).strftime('%Y-%m-%d')

class ReportCreator:
    """Creates the actual report based on given data."""
    def __init__(self):
        pass
    
    def create(self, data, path):
        self.data = data
        self.path = path

def html_linkify(text):
    return text.lower().replace(' ', '_')

def html_header(level, text):
    name = html_linkify(text)
    return '\n<h%d><a href="#%s" name="%s">%s</a></h%d>\n\n' % (level, name, name, text, level)

class HTMLReportCreator(ReportCreator):
    def create(self, data, path):
        ReportCreator.create(self, data, path)
        self.title = data.projectname

        # copy static files. Looks in the binary directory, ../share/gitstats and /usr/share/gitstats
        binarypath = os.path.dirname(os.path.abspath(__file__))
        secondarypath = os.path.join(binarypath, '..', 'share', 'gitstats')
        basedirs = [binarypath, secondarypath, '/usr/share/gitstats']
        for file in ('gitstats.css', 'sortable.js', 'arrow-up.gif', 'arrow-down.gif', 'arrow-none.gif'):
            for base in basedirs:
                src = base + '/' + file
                if os.path.exists(src):
                    shutil.copyfile(src, path + '/' + file)
                    break
            else:
                print 'Warning: "%s" not found, so not copied (searched: %s)' % (file, basedirs)

        f = open(path + "/index.html", 'w')
        format = '%Y-%m-%d %H:%M:%S'
        self.printHeader(f)

        f.write('<h1>GitStats - %s</h1>' % data.projectname)

        self.printNav(f)

        f.write('<dl>')
        f.write('<dt>Project name</dt><dd>%s</dd>' % (data.projectname))
        f.write('<dt>Generated</dt><dd>%s (in %d seconds)</dd>' % (datetime.datetime.now().strftime(format), time.time() - data.getStampCreated()))
        f.write('<dt>Generator</dt><dd><a href="http://gitstats.sourceforge.net/">GitStats</a> forked & improved '
                '<a href="https://github.com/nguyentruongtho/gitstats">https://github.com/nguyentruongtho/gitstats</a> (version %s), %s, %s</dd>' % (getversion(), getgitversion(), getgnuplotversion()))
        f.write('<dt>Report Period</dt><dd>%s to %s</dd>' % (data.getFirstCommitDate().strftime(format), data.getLastCommitDate().strftime(format)))
        f.write('<dt>Age</dt><dd>%d days, %d active days (%3.2f%%)</dd>' % (data.getCommitDeltaDays(), len(data.getActiveDays()), (100.0 * len(data.getActiveDays()) / data.getCommitDeltaDays())))
        f.write('<dt>Total Files</dt><dd>%s</dd>' % data.getTotalFiles())
        f.write('<dt>Total Lines of Code</dt><dd>%s (%d added, %d removed)</dd>' % (data.getTotalLOC(), data.total_lines_added, data.total_lines_removed))

        total_commits = data.getTotalCommits()
        if (total_commits > 0):
            f.write('<dt>Total Commits</dt><dd>%s (average %.1f commits per active day, %.1f per all days)</dd>' %
                    (total_commits, float(total_commits) / len(data.getActiveDays()), float(total_commits) / data.getCommitDeltaDays()))
        else:
            f.write('<dt>Total Commits</dt>: 0')

        total_authors = data.getTotalAuthors()
        if (total_authors > 0):
            f.write('<dt>Authors</dt><dd>%s (average %.1f commits per author)</dd>' % (data.getTotalAuthors(), (1.0 * data.getTotalCommits()) / data.getTotalAuthors()))
        else:
            f.write('<dt>Authors</dt><dd>0')

        f.write('</dl>')

        f.write('</div></body>\n</html>')
        f.close()

        ###
        # Activity
        f = open(path + '/activity.html', 'w')
        self.printHeader(f)
        f.write('<h1>Activity</h1>')
        self.printNav(f)

        #f.write('<h2>Last 30 days</h2>')

        #f.write('<h2>Last 12 months</h2>')

        # Weekly activity
        WEEKS = 32
        f.write(html_header(2, 'Weekly activity'))
        f.write('<p>Last %d weeks</p>' % WEEKS)

        # generate weeks to show (previous N weeks from now)
        now = datetime.datetime.now()
        deltaweek = datetime.timedelta(7)
        weeks = []
        stampcur = now
        for i in range(0, WEEKS):
            weeks.insert(0, stampcur.strftime('%Y-%W'))
            stampcur -= deltaweek

        # top row: commits & bar
        f.write('<table class="noborders table"><tr>')
        for i in range(0, WEEKS):
            commits = 0
            if weeks[i] in data.activity_by_year_week:
                commits = data.activity_by_year_week[weeks[i]]

            percentage = 0
            if weeks[i] in data.activity_by_year_week:
                percentage = float(data.activity_by_year_week[weeks[i]]) / data.activity_by_year_week_peak
            height = max(1, int(200 * percentage))
            f.write('<td style="text-align: center; vertical-align: bottom">%d<div style="display: block; background-color: red; width: 20px; height: %dpx"></div></td>' % (commits, height))

        # bottom row: year/week
        f.write('</tr><tr>')
        for i in range(0, WEEKS):
            f.write('<td>%s</td>' % (WEEKS - i))
        f.write('</tr></table>')

        # Hour of Day
        f.write(html_header(2, 'Hour of Day'))
        hour_of_day = data.getActivityByHourOfDay()
        f.write('<table class="static-metric table table-bordered"><tr><th>Hour</th>')
        for i in range(0, 24):
            f.write('<th>%d</th>' % i)
        f.write('</tr>\n<tr><th>Commits</th>')
        fp = open(path + '/hour_of_day.dat', 'w')
        for i in range(0, 24):
            if i in hour_of_day:
                r = 127 + int((float(hour_of_day[i]) / data.activity_by_hour_of_day_busiest) * 128)
                f.write('<td style="background-color: rgb(%d, 0, 0)">%d</td>' % (r, hour_of_day[i]))
                fp.write('%d %d\n' % (i, hour_of_day[i]))
            else:
                f.write('<td>0</td>')
                fp.write('%d 0\n' % i)
        fp.close()
        f.write('</tr>\n<tr><th>%</th>')
        total_commits = data.getTotalCommits()
        for i in range(0, 24):
            if i in hour_of_day:
                r = 127 + int((float(hour_of_day[i]) / data.activity_by_hour_of_day_busiest) * 128)
                f.write('<td style="background-color: rgb(%d, 0, 0)">%.2f</td>' % (r, (100.0 * hour_of_day[i]) / total_commits))
            else:
                f.write('<td>0.00</td>')
        f.write('</tr></table>')
        f.write('<img src="hour_of_day.png" alt="Hour of Day" />')
        fg = open(path + '/hour_of_day.dat', 'w')
        for i in range(0, 24):
            if i in hour_of_day:
                fg.write('%d %d\n' % (i + 1, hour_of_day[i]))
            else:
                fg.write('%d 0\n' % (i + 1))
        fg.close()

        # Day of Week
        f.write(html_header(2, 'Day of Week'))
        day_of_week = data.getActivityByDayOfWeek()
        f.write('<div class="vtable"><table class="table">')
        f.write('<tr><th>Day</th><th>Total (%)</th></tr>')
        fp = open(path + '/day_of_week.dat', 'w')
        for d in range(0, 7):
            commits = 0
            if d in day_of_week:
                commits = day_of_week[d]
            fp.write('%d %s %d\n' % (d + 1, WEEKDAYS[d], commits))
            f.write('<tr>')
            f.write('<th>%s</th>' % (WEEKDAYS[d]))
            if d in day_of_week:
                f.write('<td>%d (%.2f%%)</td>' % (day_of_week[d], (100.0 * day_of_week[d]) / total_commits))
            else:
                f.write('<td>0</td>')
            f.write('</tr>')
        f.write('</table></div>')
        f.write('<img src="day_of_week.png" alt="Day of Week" />')
        fp.close()

        # Hour of Week
        f.write(html_header(2, 'Hour of Week'))
        f.write('<table class="static-metric table table-bordered">')

        f.write('<tr><th>Weekday</th>')
        for hour in range(0, 24):
            f.write('<th>%d</th>' % (hour))
        f.write('</tr>')

        for weekday in range(0, 7):
            f.write('<tr><th>%s</th>' % (WEEKDAYS[weekday]))
            for hour in range(0, 24):
                try:
                    commits = data.activity_by_hour_of_week[weekday][hour]
                except KeyError:
                    commits = 0
                if commits != 0:
                    f.write('<td')
                    r = 127 + int((float(commits) / data.activity_by_hour_of_week_busiest) * 128)
                    f.write(' style="background-color: rgb(%d, 0, 0)"' % r)
                    f.write('>%d</td>' % commits)
                else:
                    f.write('<td></td>')
            f.write('</tr>')

        f.write('</table>')

        # Month of Year
        f.write(html_header(2, 'Month of Year'))
        f.write('<div class="vtable"><table class="table">')
        f.write('<tr><th>Month</th><th>Commits (%)</th></tr>')
        fp = open (path + '/month_of_year.dat', 'w')
        for mm in range(1, 13):
            commits = 0
            if mm in data.activity_by_month_of_year:
                commits = data.activity_by_month_of_year[mm]

            total_commits = data.getTotalCommits()
            if total_commits > 0:
                f.write('<tr><td>%d</td><td>%d (%.2f %%)</td></tr>' % (mm, commits, (100.0 * commits) / total_commits))

            fp.write('%d %d\n' % (mm, commits))
        fp.close()
        f.write('</table></div>')
        f.write('<img src="month_of_year.png" alt="Month of Year" />')

        # Commits by year/month
        f.write(html_header(2, 'Commits by year/month'))
        f.write('<div class="vtable"><table class="table"><tr><th>Month</th><th>Commits</th><th>Lines added</th><th>Lines removed</th></tr>')
        for yymm in reversed(sorted(data.commits_by_month.keys())):
            f.write('<tr><td>%s</td><td>%d</td><td>%d</td><td>%d</td></tr>' % (yymm, data.commits_by_month.get(yymm,0), data.lines_added_by_month.get(yymm,0), data.lines_removed_by_month.get(yymm,0)))
        f.write('</table></div>')
        f.write('<img src="commits_by_year_month.png" alt="Commits by year/month" />')
        fg = open(path + '/commits_by_year_month.dat', 'w')
        for yymm in sorted(data.commits_by_month.keys()):
            fg.write('%s %s\n' % (yymm, data.commits_by_month[yymm]))
        fg.close()

        # Commits by year
        f.write(html_header(2, 'Commits by Year'))
        f.write('<div class="vtable"><table class="table"><tr><th>Year</th><th>Commits (% of all)</th><th>Lines added</th><th>Lines removed</th></tr>')
        for yy in reversed(sorted(data.commits_by_year.keys())):
            total_commits = data.getTotalCommits()
            if total_commits > 0:
                f.write('<tr><td>%s</td><td>%d (%.2f%%)</td><td>%d</td><td>%d</td></tr>' %
                        (yy, data.commits_by_year.get(yy,0), (100.0 * data.commits_by_year.get(yy,0)) / total_commits, data.lines_added_by_year.get(yy,0), data.lines_removed_by_year.get(yy,0)))
        f.write('</table></div>')
        f.write('<img src="commits_by_year.png" alt="Commits by Year" />')
        fg = open(path + '/commits_by_year.dat', 'w')
        for yy in sorted(data.commits_by_year.keys()):
            fg.write('%d %d\n' % (yy, data.commits_by_year[yy]))
        fg.close()

        # Commits by timezone
        commits_by_timezone = data.commits_by_timezone.values()
        if commits_by_timezone:
            f.write(html_header(2, 'Commits by Timezone'))
            f.write('<table class="table"><tr>')
            f.write('<th>Timezone</th><th>Commits</th>')
            max_commits_on_tz = max(data.commits_by_timezone.values())
            for i in sorted(data.commits_by_timezone.keys(), key = lambda n : int(n)):
                commits = data.commits_by_timezone[i]
                r = 127 + int((float(commits) / max_commits_on_tz) * 128)
                f.write('<tr><th>%s</th><td style="background-color: rgb(%d, 0, 0)">%d</td></tr>' % (i, r, commits))
            f.write('</tr></table>')

        f.write('</div></body></html>')
        f.close()

        ###
        # Authors
        f = open(path + '/authors.html', 'w')
        self.printHeader(f)

        f.write('<h1>Authors</h1>')
        self.printNav(f)

        # Authors :: List of authors
        f.write(html_header(2, 'List of Authors'))

        f.write('<table class="sortable table table-bordered" id="authors">')
        f.write('<tr><th>Author</th><th>Commits (%)</th><th>+ lines</th><th>- lines</th><th>First commit</th><th>Last commit</th><th class="unsortable">Age</th><th>Active days</th><th># by commits</th></tr>')
        for author in data.getAuthors(conf['max_authors']):
            info = data.getAuthorInfo(author)
            f.write('<tr><td>%s</td><td>%d (%.2f%%)</td><td>%d</td><td>%d</td><td>%s</td><td>%s</td><td>%s</td><td>%d</td><td>%d</td></tr>' % (author, info['commits'], info['commits_frac'], info['lines_added'], info['lines_removed'], info['date_first'], info['date_last'], info['timedelta'], len(info['active_days']), info['place_by_commits']))
        f.write('</table>')

        allauthors = data.getAuthors()
        if len(allauthors) > conf['max_authors']:
            rest = allauthors[conf['max_authors']:]
            f.write('<p class="moreauthors">These didn\'t make it to the top: %s</p>' % ', '.join(rest))

        f.write(html_header(2, 'Cumulated Added Lines of Code per Author'))
        f.write('<img src="lines_of_code_by_author.png" alt="Lines of code per Author" />')
        if len(allauthors) > conf['max_authors']:
            f.write('<p class="moreauthors">Only top %d authors shown</p>' % conf['max_authors'])

        f.write(html_header(2, 'Commits per Author'))
        f.write('<img src="commits_by_author.png" alt="Commits per Author" />')
        if len(allauthors) > conf['max_authors']:
            f.write('<p class="moreauthors">Only top %d authors shown</p>' % conf['max_authors'])

        fgl = open(path + '/lines_of_code_by_author.dat', 'w')
        fgc = open(path + '/commits_by_author.dat', 'w')

        lines_by_authors = {} # cumulated added lines by
        # author. to save memory,
        # changes_by_date_by_author[stamp][author] is defined
        # only at points where author commits.
        # lines_by_authors allows us to generate all the
        # points in the .dat file.

        # Don't rely on getAuthors to give the same order each
        # time. Be robust and keep the list in a variable.
        commits_by_authors = {} # cumulated added lines by

        self.authors_to_plot = data.getAuthors(conf['max_authors'])
        for author in self.authors_to_plot:
            lines_by_authors[author] = 0
            commits_by_authors[author] = 0
        for stamp in sorted(data.changes_by_date_by_author.keys()):
            fgl.write('%d' % stamp)
            fgc.write('%d' % stamp)
            for author in self.authors_to_plot:
                if author in data.changes_by_date_by_author[stamp].keys():
                    lines_by_authors[author] = data.changes_by_date_by_author[stamp][author]['lines_added']
                    commits_by_authors[author] = data.changes_by_date_by_author[stamp][author]['commits']
                fgl.write(' %d' % lines_by_authors[author])
                fgc.write(' %d' % commits_by_authors[author])
            fgl.write('\n')
            fgc.write('\n')
        fgl.close()
        fgc.close()

        # Authors :: Author of Month
        f.write(html_header(2, 'Author of Month'))
        f.write('<table class="sortable table table-bordered" id="aom">')
        f.write('<tr><th>Month</th><th>Author</th><th>Commits (%%)</th><th class="unsortable">Next top %d</th><th>Number of authors</th></tr>' % conf['authors_top'])
        for yymm in reversed(sorted(data.author_of_month.keys())):
            authordict = data.author_of_month[yymm]
            authors = getkeyssortedbyvalues(authordict)
            authors.reverse()
            commits = data.author_of_month[yymm][authors[0]]
            next = ', '.join(authors[1:conf['authors_top']+1])
            f.write('<tr><td>%s</td><td>%s</td><td>%d (%.2f%% of %d)</td><td>%s</td><td>%d</td></tr>' % (yymm, authors[0], commits, (100.0 * commits) / data.commits_by_month[yymm], data.commits_by_month[yymm], next, len(authors)))

        f.write('</table>')

        f.write(html_header(2, 'Author of Year'))
        f.write('<table class="sortable table table-bordered" id="aoy"><tr><th>Year</th><th>Author</th><th>Commits (%%)</th><th class="unsortable">Next top %d</th><th>Number of authors</th></tr>' % conf['authors_top'])
        for yy in reversed(sorted(data.author_of_year.keys())):
            authordict = data.author_of_year[yy]
            authors = getkeyssortedbyvalues(authordict)
            authors.reverse()
            commits = data.author_of_year[yy][authors[0]]
            next = ', '.join(authors[1:conf['authors_top']+1])
            f.write('<tr><td>%s</td><td>%s</td><td>%d (%.2f%% of %d)</td><td>%s</td><td>%d</td></tr>' % (yy, authors[0], commits, (100.0 * commits) / data.commits_by_year[yy], data.commits_by_year[yy], next, len(authors)))
        f.write('</table>')

        # Domains
        f.write(html_header(2, 'Commits by Domains'))
        domains_by_commits = getkeyssortedbyvaluekey(data.domains, 'commits')
        domains_by_commits.reverse() # most first
        f.write('<div class="vtable"><table class="table">')
        f.write('<tr><th>Domains</th><th>Total (%)</th></tr>')
        fp = open(path + '/domains.dat', 'w')
        n = 0
        for domain in domains_by_commits:
            if n == conf['max_domains']:
                break
            commits = 0
            n += 1
            info = data.getDomainInfo(domain)
            fp.write('%s %d %d\n' % (domain, n , info['commits']))
            f.write('<tr><th>%s</th><td>%d (%.2f%%)</td></tr>' % (domain, info['commits'], (100.0 * info['commits'] / total_commits)))
        f.write('</table></div>')
        f.write('<img src="domains.png" alt="Commits by Domains" />')
        fp.close()

        f.write('</div></body></html>')
        f.close()

        ###
        # Files
        f = open(path + '/files.html', 'w')
        self.printHeader(f)
        f.write('<h1>Files</h1>')
        self.printNav(f)

        f.write('<dl>\n')
        f.write('<dt>Total files</dt><dd>%d</dd>' % data.getTotalFiles())
        f.write('<dt>Total lines</dt><dd>%d</dd>' % data.getTotalLOC())
        try:
            f.write('<dt>Average file size</dt><dd>%.2f bytes</dd>' % (float(data.getTotalSize()) / data.getTotalFiles()))
        except ZeroDivisionError:
            pass
        f.write('</dl>\n')

        # Files :: File count by date
        f.write(html_header(2, 'File count by date'))

        # use set to get rid of duplicate/unnecessary entries
        files_by_date = set()
        for stamp in sorted(data.files_by_stamp.keys()):
            files_by_date.add('%s %d' % (datetime.datetime.fromtimestamp(stamp).strftime('%Y-%m-%d'), data.files_by_stamp[stamp]))

        fg = open(path + '/files_by_date.dat', 'w')
        for line in sorted(list(files_by_date)):
            fg.write('%s\n' % line)
        #for stamp in sorted(data.files_by_stamp.keys()):
        #    fg.write('%s %d\n' % (datetime.datetime.fromtimestamp(stamp).strftime('%Y-%m-%d'), data.files_by_stamp[stamp]))
        fg.close()
            
        f.write('<img src="files_by_date.png" alt="Files by Date" />')

        #f.write('<h2>Average file size by date</h2>')

        # Files :: Extensions
        f.write(html_header(2, 'Extensions'))
        f.write('<table class="sortable table table-bordered" id="ext"><tr><th>Extension</th><th>Files (%)</th><th>Lines (%)</th><th>Lines/file</th></tr>')
        for ext in sorted(data.extensions.keys()):
            files = data.extensions[ext]['files']
            lines = data.extensions[ext]['lines']
            try:
                loc_percentage = (100.0 * lines) / data.getTotalLOC()
            except ZeroDivisionError:
                loc_percentage = 0
            f.write('<tr><td>%s</td><td>%d (%.2f%%)</td><td>%d (%.2f%%)</td><td>%d</td></tr>' % (ext, files, (100.0 * files) / data.getTotalFiles(), lines, loc_percentage, lines / files))
        f.write('</table>')

        f.write('</div></body></html>')
        f.close()

        ###
        # Lines
        f = open(path + '/lines.html', 'w')
        self.printHeader(f)
        f.write('<h1>Lines</h1>')
        self.printNav(f)

        f.write('<dl>\n')
        f.write('<dt>Total lines</dt><dd>%d</dd>' % data.getTotalLOC())
        f.write('</dl>\n')

        f.write(html_header(2, 'Lines of Code'))
        f.write('<img src="lines_of_code.png" />')

        fg = open(path + '/lines_of_code.dat', 'w')
        for stamp in sorted(data.changes_by_date.keys()):
            fg.write('%d %d\n' % (stamp, data.changes_by_date[stamp]['lines']))
        fg.close()

        f.write('</div></body></html>')
        f.close()

        ###
        # tags.html
        f = open(path + '/tags.html', 'w')
        self.printHeader(f)
        f.write('<h1>Tags</h1>')
        self.printNav(f)

        f.write('<dl>')
        f.write('<dt>Total tags</dt><dd>%d</dd>' % len(data.tags))
        if len(data.tags) > 0:
            f.write('<dt>Average commits per tag</dt><dd>%.2f</dd>' % (1.0 * data.getTotalCommits() / len(data.tags)))
        f.write('</dl>')

        f.write('<table class="tags table table-bordered">')
        f.write('<tr><th>Name</th><th>Date</th><th>Commits</th><th>Authors</th></tr>')
        # sort the tags by date desc
        tags_sorted_by_date_desc = map(lambda el : el[1], reversed(sorted(map(lambda el : (el[1]['date'], el[0]), data.tags.items()))))
        for tag in tags_sorted_by_date_desc:
            authorinfo = []
            self.authors_by_commits = getkeyssortedbyvalues(data.tags[tag]['authors'])
            for i in reversed(self.authors_by_commits):
                authorinfo.append('%s (%d)' % (i, data.tags[tag]['authors'][i]))
            f.write('<tr><td>%s</td><td>%s</td><td>%d</td><td>%s</td></tr>' % (tag, data.tags[tag]['date'], data.tags[tag]['commits'], ', '.join(authorinfo)))
        f.write('</table>')

        f.write('</div></body></html>')
        f.close()

        self.createGraphs(path)
    
    def createGraphs(self, path):
        print 'Generating graphs...'

        # hour of day
        f = open(path + '/hour_of_day.plot', 'w')
        f.write(GNUPLOT_COMMON)
        f.write(
"""
set output 'hour_of_day.png'
unset key
set xrange [0.5:24.5]
set xtics 4
set grid y
set ylabel "Commits"
plot 'hour_of_day.dat' using 1:2:(0.5) w boxes fs solid
""")
        f.close()

        # day of week
        f = open(path + '/day_of_week.plot', 'w')
        f.write(GNUPLOT_COMMON)
        f.write(
"""
set output 'day_of_week.png'
unset key
set xrange [0.5:7.5]
set xtics 1
set grid y
set ylabel "Commits"
plot 'day_of_week.dat' using 1:3:(0.5):xtic(2) w boxes fs solid
""")
        f.close()

        # Domains
        f = open(path + '/domains.plot', 'w')
        f.write(GNUPLOT_COMMON)
        f.write(
"""
set output 'domains.png'
unset key
unset xtics
set yrange [0:]
set grid y
set ylabel "Commits"
plot 'domains.dat' using 2:3:(0.5) with boxes fs solid, '' using 2:3:1 with labels rotate by 45 offset 0,1
""")
        f.close()

        # Month of Year
        f = open(path + '/month_of_year.plot', 'w')
        f.write(GNUPLOT_COMMON)
        f.write(
"""
set output 'month_of_year.png'
unset key
set xrange [0.5:12.5]
set xtics 1
set grid y
set ylabel "Commits"
plot 'month_of_year.dat' using 1:2:(0.5) w boxes fs solid
""")
        f.close()

        # commits_by_year_month
        f = open(path + '/commits_by_year_month.plot', 'w')
        f.write(GNUPLOT_COMMON)
        f.write(
"""
set output 'commits_by_year_month.png'
unset key
set xdata time
set timefmt "%Y-%m"
set format x "%Y-%m"
set xtics rotate
set bmargin 5
set grid y
set ylabel "Commits"
plot 'commits_by_year_month.dat' using 1:2:(0.5) w boxes fs solid
""")
        f.close()

        # commits_by_year
        f = open(path + '/commits_by_year.plot', 'w')
        f.write(GNUPLOT_COMMON)
        f.write(
"""
set output 'commits_by_year.png'
unset key
set xtics 1 rotate
set grid y
set ylabel "Commits"
set yrange [0:]
plot 'commits_by_year.dat' using 1:2:(0.5) w boxes fs solid
""")
        f.close()

        # Files by date
        f = open(path + '/files_by_date.plot', 'w')
        f.write(GNUPLOT_COMMON)
        f.write(
"""
set output 'files_by_date.png'
unset key
set xdata time
set timefmt "%Y-%m-%d"
set format x "%Y-%m-%d"
set grid y
set ylabel "Files"
set xtics rotate
set ytics autofreq
set bmargin 6
plot 'files_by_date.dat' using 1:2 w steps
""")
        f.close()

        # Lines of Code
        f = open(path + '/lines_of_code.plot', 'w')
        f.write(GNUPLOT_COMMON)
        f.write(
"""
set output 'lines_of_code.png'
unset key
set xdata time
set timefmt "%s"
set format x "%Y-%m-%d"
set grid y
set ylabel "Lines"
set xtics rotate
set bmargin 6
plot 'lines_of_code.dat' using 1:2 w lines
""")
        f.close()

        # Lines of Code Added per author
        f = open(path + '/lines_of_code_by_author.plot', 'w')
        f.write(GNUPLOT_COMMON)
        f.write(
"""
set terminal png transparent size 640,480
set output 'lines_of_code_by_author.png'
set key left top
set xdata time
set timefmt "%s"
set format x "%Y-%m-%d"
set grid y
set ylabel "Lines"
set xtics rotate
set bmargin 6
plot """
)
        i = 1
        plots = []
        for a in self.authors_to_plot:
            i = i + 1
            plots.append("""'lines_of_code_by_author.dat' using 1:%d title "%s" w lines""" % (i, a.replace("\"", "\\\"")))
        f.write(", ".join(plots))
        f.write('\n')

        f.close()

        # Commits per author
        f = open(path + '/commits_by_author.plot', 'w')
        f.write(GNUPLOT_COMMON)
        f.write(
"""
set terminal png transparent size 640,480
set output 'commits_by_author.png'
set key left top
set xdata time
set timefmt "%s"
set format x "%Y-%m-%d"
set grid y
set ylabel "Commits"
set xtics rotate
set bmargin 6
plot """
)
        i = 1
        plots = []
        for a in self.authors_to_plot:
            i = i + 1
            plots.append("""'commits_by_author.dat' using 1:%d title "%s" w lines""" % (i, a.replace("\"", "\\\"")))
        f.write(", ".join(plots))
        f.write('\n')

        f.close()

        os.chdir(path)
        files = glob.glob(path + '/*.plot')
        for f in files:
            out = getpipeoutput([gnuplot_cmd + ' "%s"' % f])
            if len(out) > 0:
                print out

    def printHeader(self, f, title = ''):
        f.write(
"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE html PUBLIC "-//W3C//DTD XHTML 1.0 Transitional//EN" "http://www.w3.org/TR/xhtml1/DTD/xhtml1-transitional.dtd">
<html xmlns="http://www.w3.org/1999/xhtml">
<head>
    <title>GitStats - %s</title>
    <link href="/assets/css/bootstrap.css" rel="stylesheet"/>
    <link href="/assets/css/bootstrap-responsive.css" rel="stylesheet"/>
    <link rel="stylesheet" href="%s" type="text/css" />
    <meta name="generator" content="GitStats %s" />
    <script type="text/javascript" src="sortable.js"></script>
    <script type="text/javascript" src="/assets/js/app.js"></script>
</head>
<body>
<div class="container">
""" % (self.title, conf['style'], getversion()))

    def printNav(self, f):
        f.write("""
<div class="navbar">
  <div class="navbar-inner">
	<ul class="nav">
		<li><a href="index.html">General</a></li>
		<li><a href="activity.html">Activity</a></li>
		<li><a href="authors.html">Authors</a></li>
		<li><a href="files.html">Files</a></li>
		<li><a href="lines.html">Lines</a></li>
		<li><a href="tags.html">Tags</a></li>
	</ul>
  </div>
</div>
""")
        
def usage():
    print """
Usage: gitstats [options] <gitpath..> <outputpath>

Options:
-c key=value     Override configuration value

Default config values:
%s

Please see the manual page for more details.
""" % conf


class GitStats:
    def run(self, args_orig):
        optlist, args = getopt.getopt(args_orig, 'hc:', ["help"])
        for o,v in optlist:
            if o == '-c':
                key, value = v.split('=', 1)
                if key not in conf:
                    raise KeyError('no such key "%s" in config' % key)
                if isinstance(conf[key], int):
                    conf[key] = int(value)
                elif isinstance(conf[key], dict):
                    kk,vv = value.split(',', 1)
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
            print 'FATAL: Output path is not a directory or does not exist'
            sys.exit(1)

        if not getgnuplotversion():
            print 'gnuplot not found'
            sys.exit(1)

        print 'Output path: %s' % outputpath
        cachefile = os.path.join(outputpath, 'gitstats.cache')

        data = GitDataCollector()
        data.loadCache(cachefile)

        if len(args) == 1:
            gitpaths = args[0:]
        else:
            gitpaths = args[0:-1]

        for gitpath in gitpaths:
            print 'Git path: %s' % gitpath

            os.chdir(gitpath)

            print 'Collecting data...'
            data.collect(gitpath)
            os.chdir(rundir)

        print 'Refining data...'
        data.saveCache(cachefile)
        data.refine()

        os.chdir(rundir)

        print 'Generating report...'
        report = HTMLReportCreator()

        single_project_output_path = os.path.join(outputpath, data.projectname)

        time_format = '%Y-%m-%d %H:%M:%S'
        single_project_output_path += \
            "(%s to %s)" % (data.getFirstCommitDate().strftime(time_format), data.getLastCommitDate().strftime(time_format))

        try:
            os.makedirs(single_project_output_path)
        except OSError:
            pass
        if not os.path.isdir(single_project_output_path):
            print 'FATAL: Unable to create output folder'
            sys.exit(1)

        report.create(data, single_project_output_path)

        time_end = time.time()
        exectime_internal = time_end - time_start
        print 'Execution time %.5f secs, %.5f secs (%.2f %%) in external commands)' % (exectime_internal, exectime_external, (100.0 * exectime_external) / exectime_internal)
        if sys.stdin.isatty():
            print 'You may now run:'
            print
            print 'sensible-browser \'%s\'' % os.path.join(outputpath, 'index.html').replace("'", "'\\''")
            print

if __name__=='__main__':
    g = GitStats()
    g.run(sys.argv[1:])


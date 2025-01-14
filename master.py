from datetime import datetime, timedelta
import importlib
from os import environ
from random import shuffle
from subprocess import check_output
from sys import stdout
from traceback import print_exc
from wikitools import wiki
from wikitools.page import Page

import open_pr_comment

# Reports I want:
# Now that I have wikitext caching, many things are faster. Write a report for Redirects which link to non-existant subsections
# Quotations which use quote characters
# Using {{lang}} and {{if lang}} on non-template pages -> this is apparently somewhat common now to make copy/paste editing easier
# Pages which link to disambig pages not in hatnote/see also
# Just... a summary of every single external link. Maybe just 'count per domain' and then list the top 10 pages? I'm finding a LOT of sus links, and it's only the ones that are *broken*.
# {{lang}} template mis-ordering and lang-template duplicate keys
# Templates sorted by usage and protect status
# A 'missing translations' report but for dictionary entries (maybe sorted by usage, too?)
# A report for "Edits on talkpages (not in the "user talk" namespace) in the past few days", so people can track active discussions?

# Reports I want to improve:
# update readme (again)
# Consider running some scripts against the Help: namespace, too
# (like what? miscategorized, mismatched, uhhh)
# Sort missing categories by # pages
# Sort the output from mismatched
# Sort the output from displaytitles
# Threading for navboxes.py?
# Ensure that PRs which add files also touch readme.md -> isn't this done?
# Templates which link to redirects

def edit_or_save(page_name, file_name, output, summary):
  wiki_diff_url = Page(w, page_name).edit(output, bot=True, summary=summary)
  if wiki_diff_url:
    return wiki_diff_url

  # Edit failed, fall back to saving to file (will be attached as a build artifact)
  with open(file_name, 'w', encoding='utf-8') as f:
    f.write(output)

  return None

def publish_report(w, module, report_name, root, summary):
  link_map = {}
  report_file_name = 'wiki_' + report_name.lower().replace(' ', '_')
  try:
    report_output = importlib.import_module(module).main(w)

    if isinstance(report_output, list):
      shuffle(report_output) # Shuffle the order so that we don't always upload the same language first, to ensure even coverage of 502s
      for lang, output in report_output:
        link_map[lang] = edit_or_save(f'{root}/{report_name}/{lang}', f'{report_file_name}_{lang}.txt', output, summary)
    else:
      link_map['en'] = edit_or_save(f'{root}/{report_name}', f'{report_file_name}.txt', report_output, summary)

  except Exception:
    print(f'Failed to update {report_name}')
    print_exc(file=stdout)

  return link_map

# Multi-language reports need frequent updates since we have many translators
daily_reports = {
  'all_articles': 'All articles',
  'missing_categories': 'Untranslated categories',
  'missing_translations': 'Missing translations',
  'untranslated_templates': 'Untranslated templates',
}

# English-only but otherwise frequently changing reports
weekly_reports = {
  'displaytitles_weekly': 'Duplicate displaytitles',
  'incorrect_redirects': 'Mistranslated redirects',
  'incorrectly_categorized': 'Pages with incorrect categorization',
  'incorrectly_linked': 'Pages with incorrect links',
  'mismatched_weekly': 'Mismatched parenthesis',
  'missing_translations_weekly': 'Missing translations/sorted',
  'navboxes': 'Pages which are missing navboxes',
  'overtranslated': 'Pages with no english equivalent',
  'wanted_templates': 'Wanted templates',
}

# Everything else (especially reports which require all HTML contents)
monthly_reports = {
  'displaytitles': 'Duplicate displaytitles',
  'duplicate_files': 'Duplicate files',
  'edit_stats': 'Users by edit count',
  'external_links2': 'External links',
  'mismatched': 'Mismatched parenthesis',
  'undocumented_templates': 'Undocumented templates',
  'unlicensed_images': 'Unlicensed images',
  'unused_files': 'Unused files',
}

all_reports = daily_reports | weekly_reports | monthly_reports

if __name__ == '__main__':
  event = environ.get('GITHUB_EVENT_NAME', 'local_run')
  modules_to_run = []

  if event == 'schedule':
    root = 'Project:Reports'
    summary = 'Automatic update via https://github.com/jbzdarkid/TFWiki-scripts'

    # Determine which reports to run -- note that the weekly and monthly cadences don't necessarily line up.
    modules_to_run += daily_reports.keys()
    if datetime.now().weekday() == 0:
      modules_to_run += weekly_reports.keys()
    if datetime.now().day == 1:
      modules_to_run += monthly_reports.keys()

  elif event == 'pull_request':
    root = f'User:{environ["WIKI_USERNAME"]}/Reports'
    summary = 'Test update via https://github.com/jbzdarkid/TFWiki-scripts'

    merge_base = check_output(['git', 'merge-base', 'HEAD', 'origin/' + environ['GITHUB_BASE_REF']], text=True).strip()
    changed_files = {f for f in check_output(['git', 'diff', '--name-only', merge_base, '--diff-filter=M'], text=True).split('\n') if f}
    added_files   = {f for f in check_output(['git', 'diff', '--name-only', merge_base, '--diff-filter=A'], text=True).split('\n') if f}

    print('Changed files:', changed_files)
    print('Added files:', added_files)

    if len(added_files) > 0 and 'README.md' not in changed_files:
      raise ValueError('When adding a new report, you must update the readme.')

    changed_files |= added_files

    if 'mismatched.py' in changed_files:
      changed_files.remove('mismatched.py')
      changed_files.add('mismatched_weekly.py')
    if 'displaytitles.py' in changed_files:
      changed_files.remove('displaytitles.py')
      changed_files.add('displaytitles_weekly.py')

    for row in changed_files:
      file = row.replace('.py', '').strip()
      if file in all_reports:
        modules_to_run.append(file)

  elif event == 'workflow_dispatch':
    root = f'User:{environ["WIKI_USERNAME"]}/Reports'
    summary = 'Test update via https://github.com/jbzdarkid/TFWiki-scripts'
    modules_to_run = all_reports.keys() # On manual triggers, run everything

  elif event == 'local_run':
    w = wiki.Wiki()
    for report in all_reports:
      # Root and summary don't matter because we can't publish anyways.
      print(report)
      publish_report(w, report, all_reports[report], '', '')
      break
    exit(0)

  else:
    print(f'Not sure what to run in response to {event}')
    exit(1)

  w = wiki.Wiki()
  if not w.login(environ['WIKI_USERNAME'], environ['WIKI_PASSWORD']):
    exit(1)

  comment = 'Please verify the following diffs:\n'
  succeeded = True

  for module in modules_to_run:
    report_name = all_reports[module]
    start = datetime.now()
    print(f'Starting {report_name} at {start}')
    link_map = publish_report(w, module, report_name, root, summary)
    duration = datetime.now() - start
    duration -= timedelta(microseconds=duration.microseconds) # Strip microseconds
    if not link_map:
      action_url = 'https://github.com/' + environ['GITHUB_REPOSITORY'] + '/actions/runs/' + environ['GITHUB_RUN_ID']
      comment += f'- [ ] {report_name} failed after {duration}: {action_url}\n'
      succeeded = False
    else:
      comment += f'- [ ] {report_name} succeeded in {duration}:'
      languages = sorted(link_map.keys(), key=lambda lang: (lang != 'en', lang)) # Sort languages, keeping english first
      for language in languages:
        link = link_map.get(language, None)
        if link:
          comment += f' [{language}]({link_map[language]})'
        else:
          comment += f' ~~[{language}](## "Upload failed")~~'
      comment += '\n'

  if event == 'pull_request':
    open_pr_comment.create_pr_comment(comment)
  elif event == 'workflow_dispatch':
    open_pr_comment.create_issue('Workflow dispatch finished', comment)
  elif environ['GITHUB_EVENT_NAME'] == 'schedule':
    print(comment)

  exit(0 if succeeded else 1)

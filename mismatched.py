from re import finditer, IGNORECASE
from unicodedata import east_asian_width as width
from utils import pagescraper_queue, time_and_date
from wikitools import wiki

pairs = [
  ['\\(', '\\)'],
  ['（', '）'],
  ['\\[', '\\]'],
  ['{', '}'],
  ['<!--', '-->'],
#  ['<([a-zA-Z]*)(?: [^>/]*)?>', '</([a-zA-Z]*?)>'], # HTML tags, e.g. <div width="2px"> </div>
]
html_tags = [
  # HTML standard
  'a', 'b', 'code', 'center', 'em', 'i', 'li', 'ol', 'p', 's', 'small', 'sub', 'sup', 'td', 'th', 'tr', 'tt', 'u', 'ul',

  # Mediawiki custom
  'gallery',
  'includeonly',
  'noinclude',
  'nowiki',
  'onlyinclude',
  'ref',
]
for tag in html_tags:
  # The tag open match needs to allow for properties, e.g. <div style="foo">
  pairs.append([f'<{tag}(?: [^>/]*)?>', f'</{tag}>'])

# Some pages are expected to have mismatched parenthesis (as they are part of the update history, item description, etc)
exemptions = {
  'Linux dedicated server': pairs[0],   # Includes a bash script with case
  'List of default keys': pairs[2],     # Includes {{Key|]}}
  'Deathcam': pairs[2],                 # Includes {{Key|[}}
  'Demoman robot': pairs[0],            # Uses :)
  'Uber Update': pairs[0],              # The update notes include 1) 2)
}

verbose = False
LANGS = ['ar', 'cs', 'da', 'de', 'en', 'es', 'fi', 'fr', 'hu', 'it', 'ja', 'ko', 'nl', 'no', 'pl', 'pt', 'pt-br', 'ro', 'ru', 'sv', 'tr', 'zh-hans', 'zh-hant']

# For regex matches which have a group, we want to include the group contents, so that we can compare pairs of HTML tags.
# For pure punctuation matches, we don't need any comparison.
def get_match_info(m):
  groups = m.groups()
  if len(groups) == 0:
    return None
  else:
    return groups[0].lower()

def pagescraper(page, translation_data):
  text = page.get_wiki_text()
  base, _, lang = page.title.rpartition('/')
  if lang not in LANGS:
    lang = 'en'
    base = page.title

  errors = []
  for pair in pairs:
    locations = []
    if pair in exemptions.get(base, []):
      continue

    for m in finditer(pair[0], text, IGNORECASE):
      match_info = get_match_info(m)
      locations.append([m.start(), +1, match_info])

    for m in finditer(pair[1], text, IGNORECASE):
      match_info = get_match_info(m)
      locations.append([m.start(), -1, match_info])

    locations.sort()

    opens = []
    in_nowiki = False
    in_comment = False
    for index, val, contents in locations:
      if contents == '<nowiki>':
        in_nowiki = True
      elif contents == '</nowiki>':
        in_nowiki = False
      elif contents == '<!--':
        in_comment = True
      elif contents == '-->':
        in_comment = False
      elif in_nowiki or in_comment:
        continue # Ignore all escaped text

      if val == +1:
        opens.append([index, contents])
      elif val == -1:
        if len(opens) == 0:
          errors.append(index) # Closing tag without a matching opening
        else:
          opens.pop() # Matching

    # Check for leftover opening tags that were not properly closed
    for index, contents in opens:
      if contents == '<noinclude>' and page.title.startswith('Template:'):
        continue # Templates may leave off the closing </noinclude>, mediawiki figures it out.

      errors.append(index)

  if len(errors) > 0:
    if verbose:
      print(f'Found {len(errors)} errors for page {page.title}')
    data = f'<h3> [{page.get_edit_url()} {page.title}] </h3>\n'
    errors.sort()
    for error in errors:
      # For display purposes, we want to highlight the mismatched symbol. To do so, we replicate the symbol on the line below, at the same horizontal offset.
      # For sanity reasons, we don't want to show too long of a line.

      start = text.rfind('\n', error-60, error) # Find the start of the line (max 80 chars behind)
      if start == -1:
        start = max(0, error-60) # Not found
      else:
        start += 1 # We don't actually want to include the \n

      # Find the next EOL, potentially including >1 line if EOL is within 20 characters.
      end = text.find('\n', start+10, start+120)
      if end == -1:
        end = start+120

      # Compute additional padding for wide characters
      widths = [width(char) for char in text[start:error]]
      extra_width = widths.count('W') # + widths.count('F')

      data += '<div class="mw-code"><nowiki>\n'
      data += text[start:end].replace('<nowiki', '&#60;nowiki') + '\n'
      extra_width = int(widths.count('W') * 0.8) # Some padding because non-ascii characters are wide
      data += ' '*(error-start+extra_width) + text[error] + ' '*10 + '\n'
      data += '</nowiki></div>\n'

    translation_data[lang].append(data)

def main(w):
  translation_data = {lang: [] for lang in LANGS}
  with pagescraper_queue(pagescraper, translation_data) as pages:
    for page in w.get_all_pages(namespaces=['Main', 'File', 'Template', 'Help', 'Category']):
      if page.title.startswith('Team Fortress Wiki:Discussion'):
        continue
      if page.title.endswith(' 3D.jpg') or page.title.endswith(' 3D.png'):
        continue
      if page.title.startswith('File:Painted '):
        continue
      if page.title.startswith('Template:PatchDiff'):
        continue
      if page.title.startswith('Template:Dictionary/items/') or page.title.startswith('Template:Dictionary/common_strings/'):
        continue # The main pages are already analyzed but we don't need to duplicate the subpages
      pages.put(page)

  output = """\
{{{{DISPLAYTITLE: {count} pages with mismatched parenthesis}}}}
<onlyinclude>{count}</onlyinclude> pages with mismatched <nowiki>(), [], and {{}}</nowiki>. Data as of {date}.
{{{{TOC limit|2}}}}

""".format(
    count=sum(len(lang_pages) for lang_pages in translation_data.values()),
    date=time_and_date())

  for language in LANGS:
    if len(translation_data[language]) > 0:
      output += '== {{lang name|name|%s}} ==\n' % language
      for data in translation_data[language]:
        output += data

  return output

if __name__ == '__main__':
  verbose = True
  w = wiki.Wiki('https://wiki.teamfortress.com/w/api.php')
  with open('wiki_mismatched_parenthesis.txt', 'w', encoding='utf-8') as f:
    f.write(main(w))
  print(f'Article written to {f.name}')

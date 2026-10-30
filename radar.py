"""Find new, unclaimed issues in open-source research projects.

Reads watchlist.json, queries the GitHub GraphQL API, and filters out issues
that already have a linked pull request, an assignee, a claim comment, or a
reporter who said they want to fix it themselves. Issues already reported are
remembered in seen.json.

Usage:
    python radar.py              # print candidates (dry run)
    python radar.py --notify     # also open a GitHub issue listing them
Requires GITHUB_TOKEN in the environment.
"""
import argparse
import json
import os
import re
import sys
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

HERE = Path(__file__).parent
API = 'https://api.github.com/graphql'

CLAIM = re.compile(
    r"(i'?d like to (work|take|pick)|i would like to (work|take)|can i (work|take|pick)|"
    r"i('ll| will) (work|take|pick|submit|open)|assign (it |this )?(to )?me|i'?m working on|"
    r"i am working on|working on (a|this|it) |opened a pr|submitted a (fix|pr)|"
    r"i have (a fix|submitted|opened)|have this working locally|happy to (send|open|submit) a pr)",
    re.I)
REPORTER_WILL_FIX = re.compile(r"\[x\]\s*i'?d be interested in making a pr", re.I)

QUERY = """
query($owner: String!, $name: String!, $since: DateTime!) {
  repository(owner: $owner, name: $name) {
    issues(states: OPEN, first: 50, orderBy: {field: CREATED_AT, direction: DESC},
           filterBy: {since: $since}) {
      nodes {
        number title url createdAt body
        author { login }
        assignees(first: 1) { totalCount }
        labels(first: 10) { nodes { name } }
        comments(first: 20) { totalCount nodes { body author { login } } }
        timelineItems(itemTypes: [CROSS_REFERENCED_EVENT, CONNECTED_EVENT], first: 20) {
          nodes { ... on CrossReferencedEvent { source { __typename } } }
        }
      }
    }
  }
}
"""


def graphql(token, query, variables):
    req = urllib.request.Request(
        API, data=json.dumps({'query': query, 'variables': variables}).encode(),
        headers={'Authorization': f'bearer {token}', 'Content-Type': 'application/json'})
    with urllib.request.urlopen(req, timeout=30) as resp:
        data = json.load(resp)
    if data.get('errors'):
        raise RuntimeError(data['errors'])
    return data['data']


def skip_reason(issue, cfg):
    """Return why an issue is not a candidate, or None if it is one."""
    if (issue['author'] or {}).get('login', '').endswith('[bot]'):
        return 'bot'
    if issue['assignees']['totalCount']:
        return 'assigned'
    if issue['comments']['totalCount'] > cfg['max_comments']:
        return 'busy'
    if any(n.get('source', {}).get('__typename') == 'PullRequest' for n in issue['timelineItems']['nodes']):
        return 'has PR'
    if REPORTER_WILL_FIX.search(issue['body'] or ''):
        return 'reporter will fix'
    if any(CLAIM.search(c['body'] or '') for c in issue['comments']['nodes']):
        return 'claimed'
    labels = {l['name'].lower() for l in issue['labels']['nodes']}
    if labels & {l.lower() for l in cfg.get('exclude_labels', [])}:
        return 'excluded label'
    return None


def find_candidates(token, cfg, seen):
    since = (datetime.now(timezone.utc) - timedelta(days=cfg['lookback_days'])).isoformat()
    found = []
    for full in cfg['repos']:
        owner, name = full.split('/')
        try:
            issues = graphql(token, QUERY, {'owner': owner, 'name': name, 'since': since})
        except Exception as e:  # one bad repo should not stop the run
            print(f'warning: {full}: {e}', file=sys.stderr)
            continue
        for issue in issues['repository']['issues']['nodes']:
            # filterBy.since matches updates too; keep only recently created issues.
            if issue['createdAt'] < since or issue['url'] in seen:
                continue
            reason = skip_reason(issue, cfg)
            if reason:
                print(f'  skip {full}#{issue["number"]} ({reason})', file=sys.stderr)
                continue
            found.append({'repo': full, **{k: issue[k] for k in ('number', 'title', 'url', 'createdAt')},
                          'comments': issue['comments']['totalCount'],
                          'labels': [l['name'] for l in issue['labels']['nodes']]})
    return found


def notify(token, repo, candidates):
    """Open one issue in the radar repo listing the candidates."""
    lines = ['New unclaimed issues in watched projects. Comment on the issue before coding.', '',
             '| Project | Issue | Opened | Comments | Labels |', '| --- | --- | --- | ---: | --- |']
    for c in candidates:
        lines.append(f"| {c['repo']} | [#{c['number']} {c['title'].replace('|', '/')}]({c['url']}) "
                     f"| {c['createdAt'][:10]} | {c['comments']} | {', '.join(c['labels']) or '-'} |")
    owner, name = repo.split('/')
    repo_id = graphql(token, 'query($o:String!,$n:String!){repository(owner:$o,name:$n){id}}',
                      {'o': owner, 'n': name})['repository']['id']
    title = f"Issue radar: {len(candidates)} new issue{'s' if len(candidates) != 1 else ''} ({datetime.now(timezone.utc):%Y-%m-%d})"
    graphql(token, 'mutation($r:ID!,$t:String!,$b:String!){createIssue(input:{repositoryId:$r,title:$t,body:$b}){issue{url}}}',
            {'r': repo_id, 't': title, 'b': '\n'.join(lines)})


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--notify', action='store_true', help='open a GitHub issue with the results')
    args = parser.parse_args()

    token = os.environ.get('GITHUB_TOKEN')
    if not token:
        sys.exit('GITHUB_TOKEN is not set')
    cfg = json.loads((HERE / 'watchlist.json').read_text())
    seen_path = HERE / 'seen.json'
    seen = set(json.loads(seen_path.read_text())) if seen_path.exists() else set()

    candidates = find_candidates(token, cfg, seen)
    for c in candidates:
        print(f"{c['repo']}#{c['number']}  {c['createdAt'][:10]}  {c['title']}\n    {c['url']}")
    if not candidates:
        print('No new candidates.')
        return
    if args.notify:
        notify(token, os.environ['GITHUB_REPOSITORY'], candidates)
        seen.update(c['url'] for c in candidates)
        seen_path.write_text(json.dumps(sorted(seen), indent=1) + '\n')


if __name__ == '__main__':
    main()

"""Read legacy interest evidence without rewriting historical participant data."""
import json


def theme_view(c,owner,prefs,revision):
    value=prefs.get('theme') or ''
    if not value:return '', 'unfilled'
    if prefs.get('theme_source')=='explicit':return value,'explicit'
    if value!='城市初访':return value,'historical_explicit'
    # The original default was 城市初访. A first saved snapshot alone is not
    # evidence that this particular field was actively chosen.
    exists=c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='personal_assistant_drafts'").fetchone()
    if exists:
        row=c.execute("SELECT 1 FROM personal_assistant_drafts WHERE owner=? AND status='confirmed' AND json_extract(payload,'$.patch.theme')=? AND CAST(json_extract(payload,'$.confirmed_revision') AS INTEGER)<=? LIMIT 1",(owner,value,revision)).fetchone()
        if row:return value,'historical_explicit'
    row=c.execute("SELECT 1 FROM personal_preferences WHERE owner=? AND revision>1 AND revision<=? AND json_extract(preferences,'$.theme')=? AND EXISTS(SELECT 1 FROM json_each(changed_fields) WHERE value='theme') LIMIT 1",(owner,revision,value)).fetchone()
    if row:return value,'historical_explicit'
    return '', 'legacy_unverified'


def effective(c,owner,prefs,revision):
    result=dict(prefs);result['theme'],result['theme_source']=theme_view(c,owner,result,revision)
    return result

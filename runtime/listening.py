"""Human listening issues are distinct from transcription results. Astra, 2026-09-09."""


def listening_status(segment, current_fingerprint, audio_stat=None, speech_rate=1.0):
    issue = segment.get('listening_issue')
    if not issue:
        return 'none'
    if segment.get('status') != 'ready':
        return 'pending'
    if (issue.get('source_fingerprint') == current_fingerprint
            and issue.get('expected_text') == (segment.get('spoken_as') or segment['text'])
            and issue.get('audio_stat') == audio_stat
            and issue.get('speech_rate',1.0) == speech_rate
            and issue.get('tempo_edit') == segment.get('tempo_edit')):
        return 'issue'
    # A different version needs listening, not an automatic quality pass.
    return 'needs_listening'

# 最后更新：2026-09-09 · Astra

import re
from collections import Counter

WORDS = {'one': 1, 'two': 2, 'three': 3, 'four': 4, 'five': 5, 'six': 6,
         'seven': 7, 'eight': 8, 'nine': 9, 'ten': 10}
NUMBER = r'(?:\d+|one|two|three|four|five|six|seven|eight|nine|ten)'


def validate_record(data, text):
    rows = data['evaluation_components']
    listed = data['total_evaluation_weight']
    data['total_listed_evaluation_weight'] = listed
    data['evaluation_selection_rules'] = []
    flat = re.sub(r'\s+', ' ', text)
    used = set()
    deduction = 0
    pattern = re.compile(rf'\bbest\s+(?:of\s+)?({NUMBER})\s+(?:[A-Za-z-]+\s+){{0,3}}?(?:out of|of)\s+(?:the\s+)?({NUMBER})\b', re.I)
    for match in pattern.finditer(flat):
        first, second = match.group(1).lower(), match.group(2).lower()
        best = int(first) if first.isdigit() else WORDS[first]
        total = int(second) if second.isdigit() else WORDS[second]
        excerpt = flat[max(0, match.start()-35):min(len(flat), match.end()+65)]
        group = 'quiz' if re.search(r'quiz', excerpt, re.I) else 'tutorial' if re.search(r'tutorial|tut test', excerpt, re.I) else None
        if not group or not 0 < best < total:
            continue
        candidates = [r for r in rows if re.search(r'quiz' if group == 'quiz' else r'tutorial|tut test', r['name'], re.I)]
        weights = [r['weight'] for r in candidates]
        ids = [r['row_number'] for r in candidates]
        applies = (len(candidates) == total and all(w is not None for w in weights)
                   and len(set(weights)) == 1 and not used.intersection(ids))
        rule = {'best_count': best, 'offered_count': total, 'component_group': group,
                'supporting_text': excerpt, 'component_rows': ids,
                'applied_to_total': applies,
                'verification_status': 'needs_verification'}
        if applies:
            deduction += (total-best)*weights[0]
            used.update(ids)
        if not any(r['best_count']==best and r['offered_count']==total and r['component_group']==group for r in data['evaluation_selection_rules']):
            data['evaluation_selection_rules'].append(rule)
    if listed is not None:
        data['total_evaluation_weight'] = round(listed-deduction, 6)
    total = data['total_evaluation_weight']
    data['evaluation_weights_sum_to_100'] = total is not None and abs(total-100) <= .1
    scheme = data.get('evaluation_scheme_text') or ''
    pass_fail = not rows and bool(re.search(r'\bPass\b', scheme, re.I) and re.search(r'\bFail\b', scheme, re.I))
    data['evaluation_scheme_kind'] = 'pass_fail' if pass_fail else 'weighted' if rows else 'unresolved'
    warnings = [w for w in data['parsing_warnings'] if not w.startswith('Evaluation weights total')]
    if pass_fail:
        warnings = [w for w in warnings if w != 'No evaluation components were extracted.']
    elif total is not None and not data['evaluation_weights_sum_to_100']:
        warnings.append(f'Evaluation weights total {total}, expected 100; verify source and selection rules.')
    data['total_extracted_marks'] = sum(r['marks'] for r in rows) if rows and all(r.get('marks') is not None for r in rows) else None
    for row in rows:
        if (row.get('declared_total_marks') and row.get('marks') is not None
                and row.get('weight_basis') == 'explicit_percentage'
                and abs(row['marks'] * 100 / row['declared_total_marks'] - row['weight']) > .1):
            warnings.append(f"Assessment row {row['row_number']}: source marks and percentage disagree.")
    if any(r['weight'] is not None and not 0 <= r['weight'] <= 100 for r in rows):
        warnings.append('An assessment percentage is outside 0–100.')
    if any(re.search(r'\b(?:BIRLA|AUGS|Pilani Campus|Grading Policy)\b', r['name'], re.I) for r in rows):
        warnings.append('Possible non-assessment text in component names.')
    data['parsing_warnings'] = list(dict.fromkeys(warnings))
    data['extraction_status'] = 'needs_ocr' if len(re.sub(r'\s+', '', text)) < 50 else 'partial' if warnings else 'extracted_unverified'
    return data


def build_report(records):
    good = [r for r in records if 'error' not in r]
    return {
        'record_count': len(records), 'file_errors': len(records)-len(good),
        'status_counts': dict(Counter(r.get('extraction_status', 'file_error') for r in records)),
        'evaluation_totals_near_100': sum(r.get('evaluation_weights_sum_to_100', False) for r in good),
        'pass_fail_schemes': sum(r.get('evaluation_scheme_kind') == 'pass_fail' for r in good),
        'missing_titles': sum(not r.get('title') for r in good),
        'missing_evaluation_components': sum(not r.get('evaluation_components') for r in good),
        'warning_counts': dict(Counter(w for r in good for w in r.get('parsing_warnings', []))),
        'review_queue': [
            {'source_file': r['source_file'], 'status': r.get('extraction_status', 'file_error'),
             'warnings': r.get('parsing_warnings', []), 'error': r.get('error')}
            for r in records if r.get('parsing_warnings') or 'error' in r
        ],
        'limitations': ['Totals are consistency checks, not semantic verification.',
                        'Unstated policies and exam absence remain unknown.',
                        'Topic vocabulary is non-exhaustive.'],
    }

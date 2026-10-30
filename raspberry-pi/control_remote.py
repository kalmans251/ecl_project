"""Allowlisted web operations mapped to existing confirmed console controls."""
VALUES = {
    'power': ('ac','battery','on','off'), 'projector': ('on','off'),
    'led': ('on','off','basic','music'), 'weather': ('clear','cloudy','rain','snow'),
    'music.mode': ('sequential','shuffle','age'), 'sleep': ('on','off'),
    'detection': ('radar','cctv'), 'query': ('p4','wroom','s3'),
}
ACTIONS = frozenset('music.'+s for s in ('start','stop','pause','resume','next')) | {'detection.count','detection.reset'}
OPERATIONS = frozenset(VALUES) | ACTIONS | {'volume','led.basic_pattern','led.music_pattern','led.sequence'}
def parts(operation, value, rail):
    if operation in VALUES:
        if value not in VALUES[operation]: raise ValueError('Unsupported control value')
    elif operation in ACTIONS:
        if value is not None: raise ValueError('Action takes no value')
    elif operation in ('volume','led.basic_pattern','led.music_pattern','led.sequence'):
        maximum={'volume':100,'led.basic_pattern':8,'led.music_pattern':2,'led.sequence':120}[operation]
        if not isinstance(value,str) or value not in {str(i) for i in range(maximum+1)}:
            raise ValueError('Invalid control range')
    else: raise ValueError('Unsupported control')
    if operation=='led.sequence' and value=='0': raise ValueError('Sequence interval must be 1..120')
    r=str(rail)
    if operation=='led.sequence': return ['led',r,'sequence',value]
    if operation=='weather': return ['led',r,'weather',value]
    if operation.endswith('_pattern'):
        return ['led',r,'basic' if operation=='led.basic_pattern' else 'music',str(int(value)+1)]
    if operation=='music.mode': return ['music',r,'mode',value]
    if operation in ('detection.count','detection.reset'): return ['detection',r,operation.split('.')[1]]
    if operation in ACTIONS: return ['music',r,operation.split('.')[1]]
    return [operation,r,value]

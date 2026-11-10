import sys,re,json,html
d=open(sys.argv[1]).read()
m=re.search(r'<pre id="out">MEASURE(.*?)ENDMEASURE</pre>',d,re.S)
r=json.loads(html.unescape(m.group(1)))
json.dump(r,open(sys.argv[2],'w'),ensure_ascii=False,indent=1)
for b in r:
    print('==',b['name'],b['size'],'primary',b['primary'],'minC',b['minContrast'])
    for s in b['screens']: print('   ',s['screen'],s['controls'],s['names'],'T',s['transient'],'area',s['cardArea'],'card',s['card'],'bar',s['bar'])
    for k in ['stray','small','overflow','clipped','lowContrast','offToken','danger','banned']:
        if b[k]: print('   ',k,b[k])

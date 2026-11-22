"""Bounded LZO1X streams used by resource loaders.

Control ranges follow the LZO1X format documented by the Linux decoder:
https://github.com/torvalds/linux/blob/master/lib/lzo/lzo1x_decompress_safe.c
"""

def unpack(data, limit=4*1024*1024):
 p=0; out=bytearray(); state=0
 def get():
  nonlocal p
  if p>=len(data):raise ValueError('input')
  b=data[p];p+=1;return b
 def literal(n):
  nonlocal p
  if p+n>len(data) or len(out)+n>limit:raise ValueError('literal bounds')
  out.extend(data[p:p+n]);p+=n
 def extend(n):
  b=get()
  while b==0:
   n+=255;b=get()
   if n>limit:raise ValueError('extent')
  return n+b
 if len(data)<3:raise ValueError('short')
 if data[0]>17:
  t=get()-17;literal(t);state=4 if t>=4 else t
 while True:
  t=get()
  if t<16:
   if state==0:
    n=extend(15) if t==0 else t
    literal(n+3);state=4;continue
   nxt=t&3;dist=(t>>2)+(get()<<2)+1
   if state==4:dist+=0x800;n=3
   else:n=2
  elif t>=64:
   nxt=t&3;dist=((t>>2)&7)+(get()<<3)+1;n=(t>>5)+1
  elif t>=32:
   n=(t&31)+2
   if n==2:n=extend(33)
   x=get()|get()<<8;dist=(x>>2)+1;nxt=x&3
  else:
   d=(t&8)<<11;n=(t&7)+2
   if n==2:n=extend(9)
   x=get()|get()<<8;d+=x>>2;nxt=x&3
   if d==0:
    if n!=3:raise ValueError('bad end')
    return bytes(out),p
   dist=d+0x4000
  if dist>len(out) or len(out)+n>limit:raise ValueError(f'bad distance {dist} at {p}')
  for _ in range(n):out.append(out[-dist])
  literal(nxt);state=nxt

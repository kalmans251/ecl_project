"""Real minimp3 header index and reservoir warmup, with generated CBR/VBR MP3s."""
from pathlib import Path
import shutil,subprocess,tempfile,unittest
MAIN=Path(__file__).resolve().parents[1]/'main'
class MusicIndexTests(unittest.TestCase):
 def test_real_cbr_vbr_duration_and_seek_pcm(self):
  self.assertIsNotNone(shutil.which('ffmpeg'),'Install ffmpeg for required MP3 seek fixtures')
  code=r'''
#include <assert.h>
#include <fcntl.h>
#include <unistd.h>
#include <stdlib.h>
#include <string.h>
#include <stdio.h>
#define MINIMP3_IMPLEMENTATION
#define MINIMP3_ONLY_MP3
#define MINIMP3_NO_SIMD
#include "minimp3.h"
#include "music_index.h"
static ssize_t rd(void *ctx,uint8_t *out,size_t n){return read(*(int *)ctx,out,n>512?512:n);}
static ssize_t cancelled(void *ctx,uint8_t *out,size_t n){(void)ctx;(void)out;(void)n;return -1;}
int main(int argc,char **argv){
 assert(argc==3);int fd=open(argv[1],O_RDONLY);assert(fd>=0);
 music_index_t idx;mp3dec_t dec;uint8_t buf[16384];
 off_t length=lseek(fd,0,SEEK_END);lseek(fd,0,SEEK_SET);
 ssize_t prefix=read(fd,buf,2048);assert(prefix>0);
 mp3dec_init(&dec);mp3dec_frame_info_t first={0};
 assert(mp3dec_decode_frame(&dec,buf,prefix,NULL,&first)>0);
 music_header_info_t header;
 bool tagged=music_header_probe(buf+first.frame_offset,prefix-first.frame_offset,length-first.frame_offset,&header);
 assert(tagged==(atoi(argv[2])!=0));
 if(tagged){assert(header.duration_ms>=240000 && header.duration_ms<240200);assert(header.hz==44100);}
 lseek(fd,0,SEEK_SET);
 assert(music_index_scan_to(&idx,&dec,buf,4608,0,rd,&fd,10000));
 assert(lseek(fd,0,SEEK_CUR)<length/2);assert(music_index_locate(&idx,10000,&(uint32_t){0},&(uint64_t){0}));
 /* Extend a prefix instead of re-reading the first ten seconds. */
 uint32_t resume=idx.next_offset;assert(resume>0);
 assert(lseek(fd,resume,SEEK_SET)==resume);
 assert(music_index_extend_to(&idx,&dec,buf,sizeof(buf),resume,rd,&fd,200000));
 assert(idx.total_samples*1000/idx.hz>200000);
 assert(music_index_cache_save(argv[1],fd,0,&idx));
 music_index_t cached={0};off_t cursor_saved=lseek(fd,0,SEEK_CUR);
 assert(music_index_cache_load(argv[1],fd,0,&cached));
 assert(lseek(fd,0,SEEK_CUR)==cursor_saved);
 assert(cached.frames==idx.frames && cached.next_offset==idx.next_offset);
 assert(!music_index_cache_load(argv[1],fd,1,&cached)); // wrong audio start
 char sidecar[1024];snprintf(sidecar,sizeof(sidecar),"%s.eclidx",argv[1]);
 FILE *bad=fopen(sidecar,"r+b");assert(bad);fputc(0,bad);fclose(bad);
 assert(!music_index_cache_load(argv[1],fd,0,&cached)); // corrupt cache is ignored
 assert(music_index_cache_save(argv[1],fd,0,&idx)); // replace previous cache
 assert(music_index_cache_load(argv[1],fd,0,&cached));
 FILE *changed=fopen(argv[1],"r+b");assert(changed);int original=fgetc(changed);
 rewind(changed);fputc(original^1,changed);fflush(changed);
 assert(!music_index_cache_load(argv[1],fd,0,&cached)); // source fingerprint mismatch
 rewind(changed);fputc(original,changed);fclose(changed);
 lseek(fd,0,SEEK_SET);
 assert(music_index_scan(&idx,&dec,buf,sizeof(buf),0,rd,&fd));
 assert(idx.ready && idx.hz==44100 && idx.count<=128 && idx.stride>=128);
 uint32_t duration=(uint32_t)(idx.total_samples*1000/idx.hz);
 assert(duration>=240000 && duration<240200);
 uint32_t offset;uint64_t sample;
 assert(!music_index_locate(&idx,duration+1,&offset,&sample));
 assert(music_index_locate(&idx,200000,&offset,&sample));assert(offset>0 && sample<200000ULL*idx.hz/1000);
 off_t size=lseek(fd,0,SEEK_END);uint8_t *all=malloc(size);assert(all);lseek(fd,0,SEEK_SET);assert(read(fd,all,size)==size);
 uint64_t target=(200000ULL*idx.hz/1000/idx.frame_samples)*idx.frame_samples;
 int16_t golden[MINIMP3_MAX_SAMPLES_PER_FRAME],pcm[MINIMP3_MAX_SAMPLES_PER_FRAME];int count=0;
 mp3dec_init(&dec);uint64_t pos=0;off_t cursor=0;
 while(cursor<size){mp3dec_frame_info_t info={0};int n=mp3dec_decode_frame(&dec,all+cursor,size-cursor,pcm,&info);assert(info.frame_bytes>0);cursor+=info.frame_bytes;
  if(info.hz>0){if(pos==target){assert(n>0);count=n*info.channels;memcpy(golden,pcm,count*sizeof(int16_t));break;}pos+=idx.frame_samples;}}
 assert(count>0);mp3dec_init(&dec);pos=sample;cursor=offset;
 while(cursor<size){mp3dec_frame_info_t info={0};int n=mp3dec_decode_frame(&dec,all+cursor,size-cursor,pcm,&info);assert(info.frame_bytes>0);cursor+=info.frame_bytes;
  if(info.hz>0){if(pos==target){assert(n*info.channels==count);assert(memcmp(golden,pcm,count*sizeof(int16_t))==0);break;}pos+=idx.frame_samples;}}
 assert(pos==target);free(all);close(fd);
 assert(!music_index_scan(&idx,&dec,buf,sizeof(buf),0,cancelled,NULL));assert(!idx.ready);
 return 0;
}
'''
  with tempfile.TemporaryDirectory() as d:
   root=Path(d);(root/'test.c').write_text(code)
   subprocess.run(['cc','-O2','-std=c11','-I',str(MAIN),str(root/'test.c'),str(MAIN/'music_index.c'),'-lm','-o',str(root/'test')],check=True)
   for encoding in (['-b:a','128k'],['-q:a','4'],['-b:a','128k','-write_xing','0']):
    path=root/'fixture.mp3'
    subprocess.run(['ffmpeg','-y','-loglevel','error','-f','lavfi','-i','sine=frequency=523:sample_rate=44100:duration=240','-ac','2','-c:a','libmp3lame',*encoding,str(path)],check=True)
    subprocess.run([str(root/'test'),str(path),'0' if '-write_xing' in encoding else '1'],check=True)

 def test_header_bounds_variants_and_malformed_metadata(self):
  code=r'''
#include <assert.h>
#include <string.h>
#define MINIMP3_IMPLEMENTATION
#define MINIMP3_NO_SIMD
#include "minimp3.h"
#include "music_index.h"
static void put(uint8_t *p,uint32_t n){for(int i=0;i<4;i++)p[i]=(uint8_t)(n>>(24-i*8));}
int main(void){
 uint8_t p[2048]={0};music_header_info_t out;
 /* MPEG1 stereo, CRC protected Xing still has fixed side-info offset. */
 p[0]=0xff;p[1]=0xfa;p[2]=0x90;memcpy(p+36,"Xing",4);put(p+40,3);put(p+44,1000);put(p+48,417000);
 assert(music_header_probe(p,sizeof(p),417000,&out));assert(out.duration_ms==26122);
 assert(!music_header_probe(p,40,417000,&out));assert(!music_header_probe(p,sizeof(p),1000,&out));
 put(p+44,0);assert(!music_header_probe(p,sizeof(p),417000,&out));
 put(p+44,1000);put(p+40,2);assert(!music_header_probe(p,sizeof(p),417000,&out));
 put(p+40,0x80000001);assert(!music_header_probe(p,sizeof(p),417000,&out));
 /* MPEG2 mono and MPEG2.5 mono; Xing location differs from MPEG1 stereo. */
 memset(p,0,sizeof(p));p[0]=0xff;p[1]=0xf3;p[2]=0x80;p[3]=0xc0;
 memcpy(p+13,"Info",4);put(p+17,1);put(p+21,1000);
 assert(music_header_probe(p,sizeof(p),417000,&out));assert(out.hz==22050 && out.frame_samples==576);
 p[1]=0xe3;assert(music_header_probe(p,sizeof(p),417000,&out));assert(out.hz==11025);
 /* VBRI version 1 at fixed +36, bounded frame count and declared file size. */
 memset(p,0,sizeof(p));p[0]=0xff;p[1]=0xfb;p[2]=0x90;
 memcpy(p+36,"VBRI",4);p[41]=1;put(p+46,417000);put(p+50,1000);
 assert(music_header_probe(p,sizeof(p),417000,&out));assert(!strcmp(out.source,"VBRI"));
 p[41]=2;assert(!music_header_probe(p,sizeof(p),417000,&out));
 memset(p,0,sizeof(p));assert(!music_header_probe(p,sizeof(p),417000,&out));return 0;
}
'''
  with tempfile.TemporaryDirectory() as d:
   root=Path(d);(root/'test.c').write_text(code)
   subprocess.run(['cc','-O2','-std=c11','-I',str(MAIN),str(root/'test.c'),str(MAIN/'music_index.c'),'-lm','-o',str(root/'test')],check=True)
   subprocess.run([str(root/'test')],check=True)

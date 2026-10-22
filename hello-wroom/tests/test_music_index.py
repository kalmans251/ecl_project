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
 assert(argc==2);int fd=open(argv[1],O_RDONLY);assert(fd>=0);
 music_index_t idx;mp3dec_t dec;uint8_t buf[16384];
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
   for encoding in (['-b:a','128k'],['-q:a','4']):
    path=root/'fixture.mp3'
    subprocess.run(['ffmpeg','-y','-loglevel','error','-f','lavfi','-i','sine=frequency=523:sample_rate=44100:duration=240','-ac','2','-c:a','libmp3lame',*encoding,str(path)],check=True)
    subprocess.run([str(root/'test'),str(path)],check=True)

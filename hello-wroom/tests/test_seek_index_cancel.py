"""Exercise the actual on-demand scan helper, with real MP3 headers and control cancellation."""
from pathlib import Path
import subprocess,tempfile,unittest
MAIN=Path(__file__).resolve().parents[1]/'main'
class SeekIndexCancelTests(unittest.TestCase):
 def test_cancel_preserves_playback_decoder_input_and_file_cursor(self):
  source=(MAIN/'music_player.c').read_text()
  helpers=source[source.index('typedef struct {\n    int fd; TickType_t deadline'):source.index('\nstatic play_result_t play_mp3_file(')]
  code=r'''
#include <assert.h>
#include <fcntl.h>
#include <stdio.h>
#include <unistd.h>
#include <string.h>
#define MINIMP3_IMPLEMENTATION
#define MINIMP3_NO_SIMD
#include "minimp3.h"
#include "music_index.h"
typedef uint32_t TickType_t;
#define pdMS_TO_TICKS(x) ((x)/10)
#define SD_READ_SIZE 512
static uint8_t s_sd_read_buffer[512],s_mp3_buffer[16384];
static int16_t s_stereo_pcm[2304];
static mp3dec_t s_decoder;
static music_index_t s_index;
static unsigned ticks,calls,cancel_at,yields;
static TickType_t xTaskGetTickCount(void){return ticks;}
static void vTaskDelay(unsigned n){ticks+=n;yields++;}
static void process_control_commands(bool *paused,bool *stop,bool *restart,char *path,size_t n){
 (void)stop;(void)restart;(void)path;(void)n;if(cancel_at && ++calls>=cancel_at)*paused=true;
}
''' + helpers + r'''
int main(void){
 FILE *f=tmpfile();assert(f);uint8_t frame[417]={0xff,0xfb,0x90,0};
 for(int i=0;i<4000;i++)assert(fwrite(frame,1,417,f)==417);
 fflush(f);int fd=fileno(f);assert(lseek(fd,7000,SEEK_SET)==7000);
 bool paused=false,stop=false,restart=false;char path[256]={0};
 memset(&s_decoder,0xa5,sizeof(s_decoder));memset(s_mp3_buffer,0x5a,sizeof(s_mp3_buffer));
 index_reader_t r={.fd=fd,.deadline=700,.paused=&paused,.stop=&stop,.restart=&restart,.path=path,.path_size=sizeof(path)};
 assert(prepare_seek_index(&r,0,10000));assert(lseek(fd,0,SEEK_CUR)==7000);
 assert(r.bytes<4000*417/2);assert(yields==0); // no artificial delay tied to bytes read
 uint32_t offset;uint64_t sample;assert(music_index_locate(&s_index,10000,&offset,&sample));
 cancel_at=3;calls=0;assert(!prepare_seek_index(&r,0,90000));assert(paused && !strcmp(r.failure,"control interrupted"));
 assert(lseek(fd,0,SEEK_CUR)==7000);assert(!s_index.ready);
 for(size_t i=0;i<sizeof(s_decoder);i++)assert(((uint8_t *)&s_decoder)[i]==0xa5);
 for(size_t i=0;i<sizeof(s_mp3_buffer);i++)assert(s_mp3_buffer[i]==0x5a);
 paused=false;cancel_at=0;ticks=700;r.failure=NULL;
 assert(!prepare_seek_index(&r,0,10000));assert(!strcmp(r.failure,"time budget exceeded"));
 assert(lseek(fd,0,SEEK_CUR)==7000);
 ticks=0;r.failure=NULL;assert(prepare_seek_index(&r,0,10000)); // explicit retry is possible
 fclose(f);return 0;
}
'''
  with tempfile.TemporaryDirectory() as d:
   root=Path(d);(root/'test.c').write_text(code)
   subprocess.run(['cc','-std=gnu11','-O2','-I',str(MAIN),str(root/'test.c'),str(MAIN/'music_index.c'),'-lm','-o',str(root/'test')],check=True)
   subprocess.run([str(root/'test')],check=True,timeout=10)

"""Exercise the production first-PCM gate: prepared selection waits without output."""
from pathlib import Path
import subprocess,tempfile,unittest
MAIN=Path(__file__).resolve().parents[1]/'main'
class SelectedPrepareTests(unittest.TestCase):
 def test_first_pcm_wait_resume_stop_and_replace(self):
  src=(MAIN/'music_player.c').read_text()
  begin=src.index('                if(s_start_confirmation.prepare_only)')
  end=src.index('\n\n\n                ESP_LOGI(',begin)
  gate=src[begin:end]
  # The gate must be before the actual audio write, not after a leaked frame.
  self.assertLess(end,src.index('!audio_output_write(',begin))
  code=r'''
#include <assert.h>
#include <stdbool.h>
#include <stddef.h>
#include "music_player.h"
#include "protocol.h"
static struct {bool prepare_only;} s_start_confirmation;
static music_player_state_t state;
static unsigned confirms,writes,waits,events;
static int action;
static void set_player_state(music_player_state_t s){state=s;}
static void confirm_operation(void *p,int status,int detail){(void)p;assert(!writes && status==0 && detail==MUSIC_PLAYER_PAUSED);confirms++;}
static void send_music_event(int e){(void)e;events++;}
static void wait_while_paused(bool *paused,bool *stop,bool *restart,char *path,size_t n){
 (void)path;(void)n;assert(*paused && state==MUSIC_PLAYER_PAUSED && confirms==1 && !writes);waits++;
 if(action==1){*paused=false;state=MUSIC_PLAYER_PLAYING;}
 else if(action==2)*stop=true;else *restart=true;
}
static void run(bool prepare,int next) {
 confirms=writes=waits=events=0;action=next;s_start_confirmation.prepare_only=prepare;
 bool paused=false,stop_requested=false,restart_requested=false;char restart_path[256];size_t restart_path_size=sizeof(restart_path);
 while(1) {
''' + gate + r'''
 writes++;break;
 }
 if(!prepare){assert(writes==1 && !waits && !confirms);return;}
 assert(waits==1 && confirms==1);
 if(next==1)assert(writes==1 && state==MUSIC_PLAYER_PLAYING);else assert(writes==0);
}
int main(void){run(true,1);run(true,2);run(true,3);run(false,1);return 0;}
'''
  with tempfile.TemporaryDirectory() as d:
   p=Path(d);(p/'test.c').write_text(code)
   subprocess.run(['cc','-std=c11','-Wall','-Wextra','-Werror','-I',str(MAIN),str(p/'test.c'),'-o',str(p/'test')],check=True)
   subprocess.run([str(p/'test')],check=True)

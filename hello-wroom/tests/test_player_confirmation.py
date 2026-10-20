"""Run actual player command consumption; enqueue alone must not acknowledge playback."""
from pathlib import Path
import subprocess,tempfile,unittest
MAIN=Path(__file__).resolve().parents[1]/'main'
class PlayerConfirmationTests(unittest.TestCase):
 def test_consumed_state_and_deferred_start(self):
  src=(MAIN/'music_player.c').read_text()
  types=src[src.index('typedef enum'):src.index('static portMUX_TYPE')]
  confirm=src[src.index('static void confirm_operation('):src.index('static player_command_t s_stop_confirmation;')]
  process=src[src.index('static void process_control_commands('):src.index('static void wait_while_paused(')]
  code=r'''
#include <assert.h>
#include <string.h>
#include "protocol.h"
#include "music_player.h"
#define MUSIC_PATH_MAX 256
#define pdTRUE 1
#define ESP_LOGI(...) ((void)0)
''' + types + r'''
static player_command_t queued,s_restart_confirmation,s_stop_confirmation;
static bool has_command;
static void *s_command_queue;
static music_player_state_t s_state;
static protocol_frame_t reply;
static unsigned replies;
static bool router_enqueue(const protocol_frame_t *f){reply=*f;replies++;return true;}
static int xQueueReceive(void *q,void *out,unsigned wait){(void)q;(void)wait;if(!has_command)return 0;*(player_command_t *)out=queued;has_command=false;return 1;}
static void send_music_event(uint8_t e){(void)e;}
static bool copy_path(char *out,size_t n,const char *s){if(strlen(s)>=n)return false;strcpy(out,s);return true;}
''' + confirm + process + r'''
static void enqueue(player_command_type_t type,uint8_t op){
 memset(&queued,0,sizeof(queued));queued.type=type;queued.confirm_operation=true;
 queued.confirm_rail=1;queued.confirm_op=op;queued.request_id[0]=42;strcpy(queued.path,"song.mp3");has_command=true;
}
int main(void){
 bool paused=false,stop=false,restart=false;char path[256];s_state=MUSIC_PLAYER_PLAYING;
 enqueue(PLAYER_CMD_PAUSE,CMD_PAUSE);assert(replies==0);
 process_control_commands(&paused,&stop,&restart,path,sizeof(path));
 assert(paused && s_state==MUSIC_PLAYER_PAUSED && replies==1 && reply.payload[5]==0);
 assert(reply.payload[0]==42 && reply.payload[4]==CMD_PAUSE);
 enqueue(PLAYER_CMD_RESUME,CMD_RESUME);process_control_commands(&paused,&stop,&restart,path,sizeof(path));
 assert(!paused && s_state==MUSIC_PLAYER_PLAYING && replies==2);
 enqueue(PLAYER_CMD_START,CMD_NEXT);process_control_commands(&paused,&stop,&restart,path,sizeof(path));
 assert(restart && replies==2 && s_restart_confirmation.confirm_operation);
 confirm_operation(&s_restart_confirmation,0,MUSIC_PLAYER_PLAYING);
 assert(replies==3 && reply.payload[4]==CMD_NEXT);
 confirm_operation(&s_restart_confirmation,0,MUSIC_PLAYER_PLAYING);assert(replies==3);
 return 0;
}
'''
  with tempfile.TemporaryDirectory() as d:
   p=Path(d);(p/'test.c').write_text(code)
   subprocess.run(['cc','-std=c11','-Wall','-Wextra','-Werror','-I',str(MAIN),str(p/'test.c'),str(MAIN/'protocol.c'),'-o',str(p/'test')],check=True)
   subprocess.run([str(p/'test')],check=True)

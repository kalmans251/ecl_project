"""Exercise the actual controller APPLY handler with modeled device dependencies."""
from pathlib import Path
import subprocess
import tempfile
import unittest

MAIN = Path(__file__).resolve().parents[1] / 'main'

class MusicApplyTests(unittest.TestCase):
    def test_validation_rejection_volume_and_deferred_stop(self):
        source = (MAIN / 'controller.c').read_text()
        start = source.index('static void handle_music_apply(')
        end = source.index('\nstatic void handle_music(', start)
        handler = source[start:end]
        harness = r'''
#include <assert.h>
#include <string.h>
#include "protocol.h"
#include "music_player.h"
#define MUSIC_SET_VOLUME 3
static bool voice, emergency, queue_ok=true;
static unsigned replies, stops, selections;
static size_t reply_len;
static uint8_t volume, response[128], saved_id[4], saved_rail;
static bool voice_session_is_active(void) { return voice; }
static bool emergency_alert_is_active(void) { return emergency; }
static void audio_output_set_volume(uint8_t v) { volume=v; }
static uint8_t audio_output_get_volume(void) { return volume; }
bool music_player_stop_confirmed(uint8_t rail,const uint8_t id[4]) {
 ++stops; saved_rail=rail; memcpy(saved_id,id,4); return queue_ok;
}
void music_player_get_info(music_player_info_t *out){
 memset(out,0,sizeof(*out));out->state=MUSIC_PLAYER_PAUSED;out->position_ms=12345;strcpy(out->filename,"a.mp3");
}
static uint32_t playlist_manager_get_catalog_version(void){return 5;}
static uint16_t playlist_manager_get_group_track_count(music_group_t g){return g==0?1:0;}
static bool playlist_manager_get_track_filename(music_group_t g,uint16_t i,char *out,size_t n){
 if(g!=0 || i!=0 || n<6)return false;
 strcpy(out,"a.mp3");return true;
}
static bool sd_manager_is_ready(void){return true;}
void music_player_confirm_selection(const uint8_t identity[7]){assert(identity[3]==5);}
static bool playlist_manager_play_selected(uint32_t v,music_group_t g,uint16_t i){
 assert(v==5 && g==0 && i==0);selections++;return queue_ok;
}
static bool playlist_manager_start(void){return true;}
static bool playlist_manager_next(void){return true;}
bool music_player_pause(void){return true;}
bool music_player_resume(void){return true;}
void music_player_confirm_begin(uint8_t rail,const uint8_t id[4],uint8_t op){(void)rail;(void)id;(void)op;}
bool music_player_confirm_end(void){return queue_ok;}
static music_play_mode_t play_mode;
static bool playlist_manager_set_mode(music_play_mode_t mode){play_mode=mode;return mode>=1 && mode<=3;}
static music_play_mode_t playlist_manager_get_mode(void){return play_mode;}
static void send_reply(const protocol_frame_t *f,uint8_t cmd,const uint8_t *p,size_t n) {
 (void)f; assert(cmd==CMD_APPLY_RESULT && n<=128); reply_len=n; memcpy(response,p,n); ++replies;
}
''' + handler + r'''
int main(void) {
 protocol_frame_t f={0}; f.src=NODE_P4;f.railing_id=1;f.payload_len=7;
 uint8_t p[7]={1,2,3,4,CMD_SET,3,20}; memcpy(f.payload,p,7);
 handle_music_apply(&f); assert(replies==1 && volume==20 && response[5]==0 && response[6]==20);
 assert(memcmp(response,p,5)==0);
 f.payload[6]=0;handle_music_apply(&f);assert(volume==0 && response[5]==0);
 f.payload[6]=101;handle_music_apply(&f);assert(volume==0 && response[5]==1);
 f.payload[6]=30;voice=true;handle_music_apply(&f);assert(volume==0 && response[5]==1);
 voice=false;emergency=true;handle_music_apply(&f);assert(volume==0 && response[5]==1);
 emergency=false;f.payload_len=5;f.payload[4]=CMD_STOP;
 unsigned before=replies;handle_music_apply(&f);
 assert(stops==1 && replies==before && saved_rail==1 && memcmp(saved_id,p,4)==0);
 queue_ok=false;handle_music_apply(&f);assert(response[5]==2 && replies==before+1);
 f.payload_len=6;before=stops;handle_music_apply(&f);assert(stops==before && response[5]==1);
 f.payload_len=5;f.payload[4]=CMD_START;queue_ok=true;before=replies;
 handle_music_apply(&f);assert(replies==before); // actual player must reply later
 queue_ok=false;handle_music_apply(&f);assert(response[5]==2);
 f.payload[4]=CMD_NEXT;queue_ok=true;before=replies;handle_music_apply(&f);assert(replies==before);
 f.payload[4]=CMD_PAUSE;handle_music_apply(&f);assert(replies==before);
 f.payload[4]=CMD_RESUME;handle_music_apply(&f);assert(replies==before);
 f.payload_len=7;f.payload[4]=CMD_SET;f.payload[5]=1;f.payload[6]=2;
 handle_music_apply(&f);assert(response[5]==0 && response[6]==2);
 f.payload_len=5;f.payload[4]=CMD_MUSIC_INFO;handle_music_apply(&f);
 assert(reply_len==17 && response[5]==0 && response[6]==MUSIC_PLAYER_PAUSED);
 assert(response[9]==0x30 && response[10]==0x39 && response[11]==5);
 f.payload[4]=CMD_MUSIC_CATALOG;handle_music_apply(&f);
 assert(reply_len==20 && response[9]==5 && response[11]==1);
 f.payload_len=12;f.payload[4]=CMD_MUSIC_TRACK;
 memset(f.payload+5,0,7);f.payload[8]=5;handle_music_apply(&f);
 assert(reply_len==19 && response[5]==0 && response[13]==5 && !memcmp(response+14,"a.mp3",5));
 f.payload[8]=4;handle_music_apply(&f);assert(reply_len==7 && response[5]==1);
 f.payload[8]=5;f.payload[4]=CMD_MUSIC_PLAY;queue_ok=true;before=replies;
 handle_music_apply(&f);assert(selections==1 && replies==before);
 f.payload[8]=4;handle_music_apply(&f);assert(selections==1 && response[5]==1);
 f.payload[8]=5;f.payload[11]=1;handle_music_apply(&f);assert(selections==1 && response[5]==1);
 f.payload[11]=0;queue_ok=false;handle_music_apply(&f);assert(response[5]==2);
 f.src=NODE_PI;before=replies;handle_music_apply(&f);assert(replies==before);
 return 0;
}
'''
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);(root/'test.c').write_text(harness)
            subprocess.run(['cc','-std=c11','-Wall','-Wextra','-Werror','-I',str(MAIN),
                            str(root/'test.c'),'-o',str(root/'test')],check=True)
            subprocess.run([str(root/'test')],check=True,timeout=5)

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
#define MUSIC_SET_VOLUME 3
static bool voice, emergency, queue_ok=true;
static unsigned replies, stops;
static uint8_t volume, response[7], saved_id[4], saved_rail;
static bool voice_session_is_active(void) { return voice; }
static bool emergency_alert_is_active(void) { return emergency; }
static void audio_output_set_volume(uint8_t v) { volume=v; }
static uint8_t audio_output_get_volume(void) { return volume; }
static bool music_player_stop_confirmed(uint8_t rail,const uint8_t *id) {
 ++stops; saved_rail=rail; memcpy(saved_id,id,4); return queue_ok;
}
static void send_reply(const protocol_frame_t *f,uint8_t cmd,const uint8_t *p,size_t n) {
 (void)f; assert(cmd==CMD_APPLY_RESULT && n==7); memcpy(response,p,n); ++replies;
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
 f.src=NODE_PI;before=replies;handle_music_apply(&f);assert(replies==before);
 return 0;
}
'''
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);(root/'test.c').write_text(harness)
            subprocess.run(['cc','-std=c11','-Wall','-Wextra','-Werror','-I',str(MAIN),
                            str(root/'test.c'),'-o',str(root/'test')],check=True)
            subprocess.run([str(root/'test')],check=True,timeout=5)

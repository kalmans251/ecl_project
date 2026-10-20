from pathlib import Path
import subprocess,tempfile,unittest
ROOT=Path(__file__).resolve().parents[1]
class S3SessionTests(unittest.TestCase):
    def test_capture_session_is_preserved_and_old_packets_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            (root/'Arduino.h').write_text('''#pragma once
#include <stdint.h>
#include <stddef.h>
struct Console { template<class... T> void println(T...){} template<class... T> void printf(T...){} };
extern Console Serial;
''')
            (root/'test.cpp').write_text(r'''
#include <cassert>
#include "audio_session.cpp"
Console Serial;
static bool mic;
static protocol_frame_t sent;
void microphone_codec2_set_enabled(bool enabled){mic=enabled;}
bool ble_send_frame(const protocol_frame_t *f){sent=*f;return true;}
int main(){
 audio_session_init();
 protocol_frame_t c={};c.src=NODE_P4;c.command=CMD_START;c.length=4;c.payload[3]=7;
 assert(audio_session_control(&c));assert(mic && audio_session_id()==7);
 uint8_t bits[48]={};
 assert(audio_session_send_codec2(bits,8,1,7));
 assert(sent.length==59 && sent.payload[10]==7 && sent.payload[5]==8);
 c.command=CMD_STOP;c.payload[3]=6;assert(!audio_session_control(&c));assert(mic);
 c.payload[3]=7;assert(audio_session_control(&c));assert(!mic);
 c.command=CMD_START;assert(!audio_session_control(&c));
 c.payload[3]=8;assert(audio_session_control(&c));assert(mic);
 assert(!audio_session_send_codec2(bits,8,2,7)); // captured under old session
 assert(audio_session_send_codec2(bits,8,0,8));assert(sent.payload[10]==8);
 c.command=CMD_SET;c.length=5;c.payload[0]=AUDIO_DIRECTION_CONTROL_TX;c.payload[3]=0;c.payload[4]=8;
 assert(audio_session_control(&c));assert(!mic);
 assert(!audio_session_send_codec2(bits,8,1,8));
 c.src=NODE_PI;assert(!audio_session_control(&c));
}
''')
            subprocess.run(['c++','-std=c++11','-Wall','-Wextra','-Werror','-I',str(root),'-I',str(ROOT/'include'),'-I',str(ROOT/'src'),str(root/'test.cpp'),'-o',str(root/'test')],check=True)
            subprocess.run([str(root/'test')],check=True)

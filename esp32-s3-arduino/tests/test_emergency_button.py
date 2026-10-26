from pathlib import Path
import subprocess,tempfile,unittest
ROOT=Path(__file__).resolve().parents[1]
class EmergencyButtonTests(unittest.TestCase):
 def test_confirmation_retries_and_release_between_holds(self):
  with tempfile.TemporaryDirectory() as d:
   p=Path(d)
   (p/'Arduino.h').write_text('''#pragma once
#include <stdint.h>
#include <stddef.h>
#define INPUT 0
#define HIGH 1
struct Log {void println(const char*){} template<class... T> void printf(const char*,T...) {}};
extern Log Serial;
uint32_t millis();int digitalRead(int);void pinMode(int,int);
''')
   (p/'esp_system.h').write_text('#include <stdint.h>\nuint32_t esp_random();\n')
   (p/'test.cpp').write_text(r'''
#include <assert.h>
#include "emergency_button.cpp"
Log Serial;static uint32_t now;static int level;static unsigned sent;static protocol_frame_t last;
uint32_t millis(){return now;}int digitalRead(int){return level;}void pinMode(int,int){}
uint32_t esp_random(){return 123;}bool ble_link_is_connected(){return true;}
bool ble_send_frame(const protocol_frame_t *f){last=*f;++sent;return true;}
void step(unsigned ms){now+=ms;emergency_button_process();}
void hold(){level=1;step(1);step(60);step(3000);}
void release(){level=0;step(1);step(60);}
int main(){
 emergency_button_init();hold();assert(sent==1 && last.command==CMD_START);
 assert(!emergency_button_is_active()); // no optimistic confirmation
 for(int i=0;i<10;++i)step(1000);assert(sent==6); // bounded, no toggle on continuous hold
 emergency_button_confirm(0x80,999);assert(!emergency_button_is_active());
 emergency_button_confirm(0x80,123);assert(emergency_button_is_active());
 emergency_button_confirm(0x81,123);release();hold();assert(last.command==CMD_STOP);
 assert(emergency_button_is_active()); // keep identity until real END
 emergency_button_confirm(0x80,123);step(1000);assert(last.command==CMD_STOP);
 emergency_button_confirm(0x82,123);assert(!emergency_button_is_active());
 unsigned n=sent;step(6000);assert(sent==n); // held button cannot immediately start again
 release();hold();assert(last.command==CMD_START && last.payload[4]==124);
 release();hold();assert(last.command==CMD_STOP); // cancel even if START confirmation lost
 emergency_button_confirm(0x82,123);assert(s_active_emergency_seq==124); // stale END ignored
 return 0;
}
''')
   subprocess.run(['c++','-std=c++11','-I',d,'-I',str(ROOT/'include'),'-I',str(ROOT/'src'),str(p/'test.cpp'),'-o',str(p/'test')],check=True)
   subprocess.run([str(p/'test')],check=True)

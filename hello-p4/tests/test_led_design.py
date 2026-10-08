"""Compile and exercise the actual renderer without ESP-IDF or physical strips."""
from pathlib import Path
import subprocess
import tempfile
import unittest
MAIN = Path(__file__).resolve().parents[1] / 'main'
HARNESS = r'''
#include <assert.h>
#include <math.h>
#include <string.h>
#include "led_design.h"
static bool lit(led_rgb_t p){return p.r || p.g || p.b;}
static unsigned count(const led_design_t *d){unsigned n=0;for(unsigned i=0;i<124;i++)n+=lit(d->pixels[0][i]);return n;}
int main(void){
 led_design_t d;uint8_t bands[8]={100,80,60,40,20,10,5,1};
 // Exact serpentine wiring, invalid coordinates never alias pixel 0.
 assert(led_design_index(0,0)==0 && led_design_index(1,0)==61);
 assert(led_design_index(3,30)==93 && led_design_index(4,0)==UINT16_MAX);
 // Basic 1: 31-pixel horizontal line, each row held for two 80ms frames.
 led_design_init(&d,1);
 assert(led_design_render(&d,0,1,0,0,false,false,bands));assert(count(&d)==31);
 assert(!led_design_render(&d,79,1,0,0,false,false,bands));
 led_design_render(&d,80,1,0,0,false,false,bands);assert(lit(d.pixels[0][0]));
 led_design_render(&d,160,1,0,0,false,false,bands);assert(lit(d.pixels[0][61]));assert(!lit(d.pixels[0][0]));
 // Basic 3: physical serpentine chase, exactly 20 nonzero pixels.
 led_design_render(&d,200,1,0,2,false,false,bands);assert(count(&d)==20);
 // Basic 4: split from center, different left/right palettes, symmetric positions.
 led_design_render(&d,300,1,0,3,false,false,bands);assert(count(&d)==4);
 assert(d.pixels[0][15].g==255 && d.pixels[1][15].b==255);
 led_design_render(&d,330,1,0,3,false,false,bands);assert(count(&d)==8);
 // Sunny auto-cycle is relative to entering the mode, with 10s dwell.
 led_design_render(&d,12345,2,0,0,false,false,bands);assert(d.sunny_pattern==0);
 led_design_render(&d,22344,2,0,0,false,false,bands);assert(d.sunny_pattern==0);
 led_design_render(&d,22345,2,0,0,false,false,bands);assert(d.sunny_pattern==1);
 // Rain: all 15 odd columns, upper row first, then next row with 40% trails.
 led_design_render(&d,25000,2,2,0,false,false,bands);assert(count(&d)==15);
 unsigned i=led_design_index(3,1);assert(d.pixels[0][i].r==255 && d.pixels[0][i].g==220);
 led_design_render(&d,25200,2,2,0,false,false,bands);assert(d.pixels[0][i].r==102);
 assert(lit(d.pixels[0][led_design_index(2,1)]));assert(!lit(d.pixels[0][led_design_index(2,0)]));
 // Snow: random sparkle spacing/lifetime, mirrored sides, bounded pool.
 led_design_render(&d,30000,2,3,0,false,false,bands);
 for(unsigned frame=1;frame<400;frame++){
  led_design_render(&d,30000+25*frame,2,3,0,false,false,bands);
  assert(memcmp(d.pixels[0],d.pixels[1],sizeof(d.pixels[0]))==0);
  for(unsigned a=0;a<18;a++)if(d.sparks[a].active)for(unsigned b=a+1;b<18;b++)if(d.sparks[b].active){
    int dr=(int)d.sparks[a].row-d.sparks[b].row,dc=(int)d.sparks[a].col-d.sparks[b].col;
    if(dr<0)dr=-dr;if(dc<0)dc=-dc;
    assert(dr+dc>=3 && !(dr<=1 && dc<=1));
  }
 }
 // Each music shape is lit, symmetric between panels, clears stale EQ immediately.
 for(unsigned pattern=0;pattern<3;pattern++){
  led_design_render(&d,50000+pattern*100,3,0,pattern,false,true,bands);assert(count(&d)>0);
  assert(memcmp(d.pixels[0],d.pixels[1],sizeof(d.pixels[0]))==0);
  assert(led_design_render(&d,50001+pattern*100,3,0,pattern,false,false,bands));assert(count(&d)==0);
  assert(!led_design_render(&d,50002+pattern*100,3,0,pattern,false,false,bands));
 }
 // Alert takes precedence over missing music data but still honors its 300ms cadence.
 assert(led_design_render(&d,60000,3,0,2,true,false,bands));assert(count(&d)==124);
 assert(!led_design_render(&d,60299,3,0,2,true,false,bands));
 assert(led_design_render(&d,60300,3,0,2,true,false,bands));assert(count(&d)==0);
 // Timer arithmetic survives uint32 wrap; unsupported input cannot mutate a frame.
 led_design_init(&d,1);led_design_render(&d,UINT32_MAX-20,1,0,0,false,false,bands);
 assert(!led_design_render(&d,20,1,0,0,false,false,bands));
 assert(led_design_render(&d,60,1,0,0,false,false,bands));
 led_design_t before=d;assert(!led_design_render(&d,100,1,0,6,false,false,bands));assert(memcmp(&d,&before,sizeof(d))==0);
 return 0;
}
'''
class LedDesignTests(unittest.TestCase):
    def test_geometry_timing_weather_music_and_transitions(self):
        with tempfile.TemporaryDirectory() as temp:
            source = Path(temp) / 'test.c'
            source.write_text(HARNESS.replace('if(dr<0)dr=-dr;if(dc<0)dc=-dc;', 'if(dr<0)dr=-dr;\n    if(dc<0)dc=-dc;'))
            output = Path(temp) / 'test'
            subprocess.run(['cc', '-std=c11', '-Wall', '-Wextra', '-Werror', '-fsanitize=undefined',
                            '-I'+str(MAIN), str(source), str(MAIN/'led_design.c'), '-lm', '-o', str(output)], check=True)
            subprocess.run([str(output)], check=True)
if __name__ == '__main__':
    unittest.main()

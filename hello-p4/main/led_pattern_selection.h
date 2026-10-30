#pragma once
#include <stdint.h>
typedef struct {uint8_t mode,weather,pattern;} led_pattern_selection_t;
/* BASIC 0..8 are the nine choices; 9 selects a repeating local sequence. */
static inline led_pattern_selection_t led_pattern_select(uint8_t mode,uint8_t weather,uint8_t pattern,uint32_t elapsed_ms,uint8_t seconds){
 led_pattern_selection_t out={mode,weather,pattern};
 if(mode==1){
  if(pattern==9)out.pattern=(elapsed_ms/(1000U*(seconds?seconds:10)))%9;
  if(out.pattern>=6&&out.pattern<=8){out.mode=2;out.weather=out.pattern==6?0:out.pattern==7?2:3;out.pattern=0;}
 }
 return out;
}

#include "music_index.h"
#include <string.h>
#include <limits.h>
bool music_index_scan(music_index_t *idx, mp3dec_t *decoder, uint8_t *buffer,
                      size_t capacity, uint32_t start, music_index_read_fn read_fn, void *ctx)
{
    memset(idx,0,sizeof(*idx));idx->stride=64;
    mp3dec_init(decoder);
    size_t used=0;uint64_t offset=start;bool eof=false;
    if(capacity<4096)return false;
    for(;;) {
        while(!eof && used<capacity) {
            ssize_t n=read_fn(ctx,buffer+used,capacity-used);
            if(n<0)return false;
            if(!n){eof=true;break;}
            used+=(size_t)n;
        }
        if(!used)break;
        mp3dec_frame_info_t info={0};
        int samples=mp3dec_decode_frame(decoder,buffer,(int)used,NULL,&info);
        if(info.frame_bytes<0 || (size_t)info.frame_bytes>used)return false;
        if(samples>0) {
            if(info.layer!=3 || info.hz<=0)return false;
            if(!idx->hz){idx->hz=info.hz;idx->frame_samples=samples;}
            if(idx->hz!=(uint32_t)info.hz || idx->frame_samples!=(uint32_t)samples)return false;
            if(idx->frames%idx->stride==0) {
                if(idx->count==MUSIC_INDEX_POINTS) {
                    for(unsigned i=0;i<MUSIC_INDEX_POINTS/2;i++){
                        idx->offsets[i]=idx->offsets[i*2];idx->samples[i]=idx->samples[i*2];
                    }
                    idx->count/=2;idx->stride*=2;
                }
                if(idx->frames%idx->stride==0){
                    if(offset+(uint32_t)info.frame_offset>UINT32_MAX)return false;
                    idx->offsets[idx->count]=(uint32_t)offset+info.frame_offset;
                    idx->samples[idx->count++]=idx->total_samples;
                }
            }
            idx->total_samples+=(unsigned)samples;idx->frames++;
            if(idx->total_samples*1000/idx->hz>UINT32_MAX)return false;
        }
        size_t consumed=info.frame_bytes>0?(size_t)info.frame_bytes:(eof?used:used-4);
        if(!consumed)return false;
        memmove(buffer,buffer+consumed,used-consumed);used-=consumed;offset+=consumed;
    }
    idx->ready=idx->count>0 && idx->total_samples>0;
    return idx->ready;
}
bool music_index_locate(const music_index_t *idx,uint32_t target_ms,uint32_t *offset,uint64_t *sample)
{
    if(!idx->ready || (uint64_t)target_ms*idx->hz/1000>=idx->total_samples)return false;
    uint64_t target=(uint64_t)target_ms*idx->hz/1000;
    /* Decode/discard enough preceding frames to rebuild Layer III reservoir and filters. */
    uint64_t warmup=(uint64_t)idx->frame_samples*256;
    uint64_t start=target>warmup?target-warmup:0;
    unsigned chosen=0;
    for(unsigned i=1;i<idx->count && idx->samples[i]<=start;i++)chosen=i;
    *offset=idx->offsets[chosen];*sample=idx->samples[chosen];return true;
}

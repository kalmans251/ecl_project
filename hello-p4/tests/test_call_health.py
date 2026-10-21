"""Read-only endpoint supervision, stale replies and conservative stop."""
from test_hangup import HARNESS
import test_hangup
HEALTH = HARNESS[:HARNESS.index('int main(void)')] + r''' 
static protocol_frame_t health(uint8_t node,uint8_t status) {
    protocol_frame_t f={.railing_id=RAILING_ID,.src=node,.dst=NODE_P4,
      .service=SERVICE_AUDIO,.command=CMD_DATA,.length=16,
      .payload={AUDIO_DATA_HEALTH,CMD_SET}};
    f.payload[2]=s_target;f.payload[3]=status;put_session(f.payload+4,s_session);
    put_session(f.payload+8,s_ptt_request);put_session(f.payload+12,s_health_token);
    return f;
}
static void start(uint32_t sid) {
    assert(call_manager_bind_session(sid));assert(call_manager_start(CALL_ORIGIN_NORMAL));
    both();call_manager_bind_session(sid);assert(!s_preparing);
    now+=1000000;call_manager_tick();assert(s_health_pending);
    assert(last.command==CMD_CALL_HEALTH && last.length==13 && last.dst==NODE_S3);
}
int main(void) {
    now=100;system_state_init();call_manager_init();start(101);
    protocol_frame_t a=health(NODE_WROOM,1),b=health(NODE_S3,1);
    a.payload[15]++;call_manager_handle_readiness(&a);assert(s_health_mask==0);
    a=health(NODE_WROOM,1);a.railing_id++;call_manager_handle_readiness(&a);assert(s_health_mask==0);
    a=health(NODE_WROOM,1);call_manager_handle_readiness(&a);
    call_manager_handle_readiness(&b);assert(!s_health_pending && !s_preparing);
    now+=1000000;call_manager_tick();assert(s_health_pending);
    call_manager_handle_readiness(&a);call_manager_handle_readiness(&b);assert(s_health_mask==0);
    a=health(NODE_WROOM,1);call_manager_handle_readiness(&a);
    uint32_t token=s_health_token;now+=500000;call_manager_tick();
    assert(last.dst==NODE_S3 && last.command==CMD_CALL_HEALTH && s_health_token==token);
    now+=2500000;call_manager_tick();assert(s_fault_stopping && s_preparing && s_operation==CMD_STOP);
    assert(fault.payload[8]==NODE_S3 && fault.payload[9]==3 && terminal_count==0);
    int64_t lease=s_call_lease_until_us;call_manager_keepalive();assert(s_call_lease_until_us==lease);
    assert(!call_manager_set_direction_ordered(101,1,AUDIO_DIRECTION_CONTROL_TX));
    report(NODE_WROOM,1);now+=5000000;call_manager_tick();assert(call_manager_is_active());
    assert(terminal_count==0); // unavailable S3 is never assumed stopped
    report(NODE_S3,1);unsigned before=sent;call_manager_tick();
    assert(!call_manager_is_active() && terminal_count==1 && sent==before);
    call_manager_tick();assert(terminal_count==1); // no repeated automatic END
    start(102);b=health(NODE_S3,2);call_manager_handle_readiness(&b);
    assert(s_fault_stopping && fault.payload[8]==NODE_S3 && fault.payload[9]==2);
    both();call_manager_tick();assert(!call_manager_is_active());
    start(103);a=health(NODE_WROOM,2);
    assert(call_manager_set_direction_ordered(103,1,AUDIO_DIRECTION_CONTROL_TX));
    call_manager_handle_readiness(&a);assert(!s_fault_stopping); // superseded probe
    both();call_manager_set_direction_ordered(103,1,AUDIO_DIRECTION_CONTROL_TX);
    now+=1000000;call_manager_tick();a=health(NODE_WROOM,2);
    call_manager_handle_readiness(&a);assert(s_fault_stopping && fault.payload[8]==NODE_WROOM);
    assert(!call_manager_control_grants_enabled());
    return 0;
}
'''
class HealthTests(test_hangup.HangupTests):
    def test_duplicate_stop_and_recovery_expiration(self):
        previous=test_hangup.HARNESS
        try:
            test_hangup.HARNESS=HEALTH
            super().test_duplicate_stop_and_recovery_expiration()
        finally:
            test_hangup.HARNESS=previous

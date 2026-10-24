"""Real C manager completes first commands without requiring retransmission."""
import test_hangup

FIRST_REPLY = test_hangup.HARNESS[:test_hangup.HARNESS.index('int main(void)')] + r'''
static void tick_ready(void) { both();call_manager_tick(); }
int main(void) {
    now=100;system_state_init();call_manager_init();
    assert(call_manager_bind_session(101));assert(call_manager_start(CALL_ORIGIN_NORMAL));
    unsigned before=sent;
    report(NODE_WROOM,1);call_manager_tick();assert(sent==before && s_preparing);
    report(NODE_S3,1);call_manager_tick();
    assert(!s_preparing && last.dst==NODE_PI && last.payload[1]==AUDIO_EVENT_CALL_STARTED);
    before=sent;both();call_manager_tick();assert(sent==before); // no duplicate ready notification
    assert(!call_manager_bind_session(101));assert(sent==before+1); // lost ACK replay
    for(uint32_t request=1;request<=2;request++) {
        uint8_t direction=request==1?AUDIO_DIRECTION_CONTROL_TX:AUDIO_DIRECTION_FIELD_TX;
        assert(call_manager_set_direction_ordered(101,request,direction));
        protocol_frame_t stale={.railing_id=RAILING_ID,.src=NODE_S3,.dst=NODE_P4,
            .service=SERVICE_AUDIO,.command=CMD_DATA,.length=12,
            .payload={AUDIO_DATA_READY,CMD_SET,0,1}};
        stale.payload[2]=direction;put_session(stale.payload+4,101);
        put_session(stale.payload+8,request-1);
        call_manager_handle_readiness(&stale);assert(s_ready_mask==0);
        tick_ready();assert(!s_preparing && call_manager_get_state()==direction);
        assert(last.dst==NODE_PI && last.payload[1]==AUDIO_EVENT_DIRECTION_CHANGED && last.payload[11]==request);
        before=sent;call_manager_tick();assert(sent==before);
        assert(call_manager_set_direction_ordered(101,request,direction));assert(sent==before+1);
    }
    assert(call_manager_stop_session(101));unsigned m=removes;
    tick_ready();assert(!call_manager_is_active() && terminal_count==1 && removes==m+1);
    assert(last.dst==NODE_PI && last.payload[1]==AUDIO_EVENT_CALL_ENDED);
    before=sent;call_manager_tick();assert(sent==before && removes==m+1);
    assert(call_manager_stop_session(101));assert(sent==before+1 && removes==m+1);

    // Slow preparation is completed by a retry, not an unsolicited late reply.
    assert(call_manager_bind_session(102));assert(call_manager_start(CALL_ORIGIN_NORMAL));
    now+=CALL_FIRST_REPLY_US;both();before=sent;call_manager_tick();
    assert(s_preparing && last.dst!=NODE_PI); // only endpoint probes may be sent
    assert(!call_manager_bind_session(102));assert(!s_preparing && last.dst==NODE_PI);
    assert(call_manager_set_direction_ordered(102,1,AUDIO_DIRECTION_CONTROL_TX));
    report(NODE_S3,2);report(NODE_WROOM,1);before=sent;call_manager_tick();
    assert(s_preparing && sent==before); // failure must never confirm success
    assert(call_manager_stop_session(102));tick_ready();assert(!call_manager_is_active());

    // Lease expiry has no current requester: retain END for polling only.
    assert(call_manager_bind_session(103));assert(call_manager_start(CALL_ORIGIN_NORMAL));tick_ready();
    now+=CALL_LEASE_US;call_manager_tick();assert(s_operation==CMD_STOP && s_stop_polled_only);
    both();before=sent;call_manager_tick();assert(!call_manager_is_active() && sent==before);
    assert(terminal.payload[1]==AUDIO_EVENT_CALL_ENDED);
    return 0;
}
'''

class FirstReplyTests(test_hangup.HangupTests):
    def test_duplicate_stop_and_recovery_expiration(self):
        previous = test_hangup.HARNESS
        try:
            test_hangup.HARNESS = FIRST_REPLY
            super().test_duplicate_stop_and_recovery_expiration()
        finally:
            test_hangup.HARNESS = previous

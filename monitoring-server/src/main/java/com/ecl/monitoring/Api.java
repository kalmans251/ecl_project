package com.ecl.monitoring;
import java.util.*;
import org.springframework.web.bind.annotation.*;
@RestController
public class Api {
    private final Events events;
    private final Gateways gateways;
    private final Settings settings;
    public Api(Events events, Gateways gateways, Settings settings) { this.events=events; this.gateways=gateways; this.settings=settings; }
    @PostMapping("/api/analytics/events") public Map<String,Object> event(@RequestBody Events.Input input) { return events.submit(input); }
    @GetMapping("/api/events/{id}") public Map<String,Object> status(@PathVariable String id) { return events.find(id); }
    @GetMapping("/api/gateways") public List<Map<String,Object>> gateways() { return gateways.status(settings); }
}

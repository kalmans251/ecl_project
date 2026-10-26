package com.ecl.monitoring;

import java.security.Principal;
import java.util.*;
import org.springframework.web.bind.annotation.*;
import org.springframework.scheduling.annotation.Scheduled;
import tools.jackson.databind.json.JsonMapper;

/** Short lived, permission checked viewer leases; never creates a PLC reader. */
@RestController
public class StatusDemand {
    public record Input(String view, List<String> rails) {}
    private record Lease(String user,List<String> rails,long until) {}
    private final Map<String,Lease> leases=new HashMap<>();
    private final Set<String> previous=new HashSet<>();
    private final Registry registry; private final Accounts accounts; private final Gateways gateways;
    private final JsonMapper json=JsonMapper.builder().build();
    public StatusDemand(Registry registry,Accounts accounts,Gateways gateways){this.registry=registry;this.accounts=accounts;this.gateways=gateways;}
    @PostMapping("/api/portal/status-demand")
    public synchronized Map<String,Boolean> demand(Principal principal,@RequestBody Input input){
        if(input.view()==null || input.view().length()>64 || input.rails()==null || input.rails().size()>255)throw Accounts.bad("Invalid status demand");
        String user=principal.getName(),key=user+":"+input.view();
        leases.values().removeIf(l->l.until()<System.nanoTime());
        if(!leases.containsKey(key) && leases.size()>=1024)throw Accounts.bad("Too many status views");
        for(String id:input.rails())accounts.permit(user,(String)registry.rail(id).get("SITE_ID"),false);
        if(input.rails().isEmpty())leases.remove(key);
        else leases.put(key,new Lease(user,List.copyOf(input.rails()),System.nanoTime()+6_000_000_000L));
        return Map.of("accepted",true);
    }
    @Scheduled(fixedDelay=2000)
    public synchronized void refresh(){
        Map<String,Set<Integer>> requested=new HashMap<>();
        leases.values().removeIf(l->l.until()<System.nanoTime());
        for(var lease:leases.values())for(String id:lease.rails())try{
            var rail=registry.rail(id);accounts.permit(lease.user(),(String)rail.get("SITE_ID"),false);
            requested.computeIfAbsent((String)rail.get("GATEWAY_ID"),k->new TreeSet<>()).add(((Number)rail.get("NUMBER")).intValue());
        }catch(Exception ignored){}
        Set<String> all=new HashSet<>(previous);all.addAll(requested.keySet());
        for(String gateway:all)try{gateways.send(gateway,json.writeValueAsString(Map.of("version",1,"type","status.demand","rails",requested.getOrDefault(gateway,Set.of()))));}catch(Exception ignored){}
        previous.clear();previous.addAll(requested.keySet());
    }
}

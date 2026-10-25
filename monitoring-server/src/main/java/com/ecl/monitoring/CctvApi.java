package com.ecl.monitoring;
import java.security.Principal;
import java.util.*;
import jakarta.servlet.http.HttpServletRequest;
import org.springframework.web.bind.annotation.*;
import tools.jackson.databind.JsonNode;

@RestController
public class CctvApi {
 private final Cctv cctv;private final CameraSocket sockets;private final Events events;
 public CctvApi(Cctv cctv,CameraSocket sockets,Events events){this.cctv=cctv;this.sockets=sockets;this.events=events;}
 public record Provision(String control_token,String publish_token,String analysis_token){}
 @PutMapping("/api/portal/admin/cctv/{camera}") public void provision(Principal p,@PathVariable String camera,@RequestBody Provision v){cctv.provision(p.getName(),camera,v.control_token(),v.publish_token(),v.analysis_token());sockets.refresh();}
 public record Enabled(boolean enabled){}
 @PutMapping("/api/portal/cctv/{camera}/enabled") public void enabled(Principal p,@PathVariable String camera,@RequestBody Enabled v){cctv.enable(p.getName(),camera,v.enabled());sockets.refresh();}
 @GetMapping("/api/portal/cctv/{camera}") public Map<String,Object> status(Principal p,@PathVariable String camera){cctv.permit(p.getName(),camera,false);return Map.of("camera",cctv.status(camera),"device",sockets.status(camera));}
 public record View(String lease){}
 @PostMapping("/api/portal/cctv/{camera}/view") public Map<String,Object> view(Principal p,HttpServletRequest q,@PathVariable String camera,@RequestBody View v){var result=cctv.view(p.getName(),q.getSession().getId(),camera,v.lease());sockets.refresh();return result;}
 @DeleteMapping("/api/portal/cctv/view/{lease}") public void release(Principal p,HttpServletRequest q,@PathVariable String lease){cctv.release(p.getName(),q.getSession().getId(),lease);sockets.refresh();}
 @GetMapping("/api/cctv/analysis/{camera}/state") public Map<String,Object> analysis(@PathVariable String camera){return cctv.status(camera);}
 @PostMapping("/api/cctv/analysis/{camera}/events") public Map<String,Object> event(@PathVariable String camera,@RequestBody Events.Input input){if(!camera.equals(input.camera_id())||!cctv.analysis(camera))throw Accounts.bad("Analysis disabled or camera mismatch");return events.submit(input);}
 @PostMapping("/api/cctv/analysis/{camera}/observation") public void observe(@PathVariable String camera,@RequestBody JsonNode n){
  if(n.size()!=3||!n.path("available").isBoolean()||!n.path("people").isInt()||n.path("people").asInt()<0||n.path("people").asInt()>1000||!Set.of("ready","disabled","unavailable","pending").contains(n.path("age").asText()))throw Accounts.bad("Invalid observation");
  if(!cctv.analysis(camera))throw Accounts.bad("Analysis disabled");cctv.observe(camera,Map.of("available",n.path("available").asBoolean(),"people",n.path("people").asInt(),"age",n.path("age").asText()));
 }
 @PostMapping("/api/cctv/media-auth") public Map<String,Object> media(@RequestBody JsonNode n){String token=n.path("token").asText();if(token.isEmpty())token=n.path("password").asText();return cctv.media(n.path("action").asText(),n.path("path").asText(),n.path("protocol").asText(),token,n.path("id").asText());}
}

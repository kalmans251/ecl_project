package com.ecl.monitoring;
import java.util.Map;
import org.springframework.web.bind.annotation.*;
import org.springframework.http.ResponseEntity;
import org.springframework.web.server.ResponseStatusException;
@RestControllerAdvice
public class PortalErrors {
    @ExceptionHandler(ResponseStatusException.class) public ResponseEntity<Map<String,Object>> error(ResponseStatusException e){return ResponseEntity.status(e.getStatusCode()).body(Map.of("status",e.getStatusCode().value(),"message",e.getReason()==null?"Request not permitted":e.getReason()));}
}

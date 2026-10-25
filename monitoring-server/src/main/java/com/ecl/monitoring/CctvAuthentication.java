package com.ecl.monitoring;
import jakarta.servlet.*;
import jakarta.servlet.http.*;
import java.io.*;
import java.util.*;
import org.springframework.web.filter.OncePerRequestFilter;

public class CctvAuthentication extends OncePerRequestFilter {
 private final Cctv cctv;
 public CctvAuthentication(Cctv cctv){this.cctv=cctv;}
 @Override protected void doFilterInternal(HttpServletRequest q,HttpServletResponse r,FilterChain chain)throws IOException,ServletException{
  String path=q.getRequestURI();
  if(q.getHeader("Origin")!=null){r.sendError(403);return;}
  if(path.equals("/api/cctv/media-auth")){
   if(!q.getMethod().equals("POST")||!Set.of("127.0.0.1","::1","0:0:0:0:0:0:0:1").contains(q.getRemoteAddr())){r.sendError(403);return;}
  }else{
   String camera,purpose;
   if(path.matches("/ws/cameras/[A-Za-z0-9_-]{1,80}")&&q.getMethod().equals("GET")){camera=path.substring(12);purpose="control";}
   else if(path.matches("/api/cctv/analysis/[A-Za-z0-9_-]{1,80}/(state|events|observation)")){camera=path.split("/")[4];purpose="analysis";}
   else{r.sendError(404);return;}
   String h=q.getHeader("Authorization");
   if(!cctv.auth(camera,purpose,h!=null&&h.startsWith("Bearer ")?h.substring(7):null)){r.sendError(401);return;}
  }
  if(q.getContentLengthLong()>4096){r.sendError(413);return;}
  chain.doFilter(new HttpServletRequestWrapper(q){
   @Override public ServletInputStream getInputStream()throws IOException{
    var input=q.getInputStream();return new ServletInputStream(){int n;
     public int read()throws IOException{int v=input.read();if(v>=0&&++n>4096)throw new IOException("Body too large");return v;}
     public boolean isFinished(){return input.isFinished();}public boolean isReady(){return input.isReady();}public void setReadListener(ReadListener l){input.setReadListener(l);}
    };
   }
  },r);
 }
}

package com.ecl.monitoring;
import org.springframework.context.annotation.*;
import org.springframework.web.socket.config.annotation.*;
import org.springframework.web.socket.server.standard.ServletServerContainerFactoryBean;
@Configuration
@EnableWebSocket
public class WebConfiguration implements WebSocketConfigurer {
    private final DeviceSocket socket;private final Voice voice;private final CameraSocket camera;
    public WebConfiguration(DeviceSocket socket,Voice voice,CameraSocket camera) { this.socket=socket;this.voice=voice;this.camera=camera; }
    @Override public void registerWebSocketHandlers(WebSocketHandlerRegistry registry) {
        registry.addHandler(camera,"/ws/cameras/*");
        registry.addHandler(socket,"/ws/gateways/*");
        registry.addHandler(voice,"/ws/operator/voice/*").addInterceptors(new org.springframework.web.socket.server.support.HttpSessionHandshakeInterceptor());
    }
    @Bean public ServletServerContainerFactoryBean webSocketContainer() {
        var container=new ServletServerContainerFactoryBean();
        container.setMaxTextMessageBufferSize(4096); container.setMaxBinaryMessageBufferSize(4096);
        container.setMaxSessionIdleTimeout(60000L); container.setAsyncSendTimeout(1000L);
        return container;
    }
}

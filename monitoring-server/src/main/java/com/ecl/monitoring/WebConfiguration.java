package com.ecl.monitoring;
import org.springframework.context.annotation.*;
import org.springframework.web.socket.config.annotation.*;
import org.springframework.web.socket.server.standard.ServletServerContainerFactoryBean;
@Configuration
@EnableWebSocket
public class WebConfiguration implements WebSocketConfigurer {
    private final DeviceSocket socket;
    public WebConfiguration(DeviceSocket socket) { this.socket=socket; }
    @Override public void registerWebSocketHandlers(WebSocketHandlerRegistry registry) {
        registry.addHandler(socket,"/ws/gateways/*");
    }
    @Bean public ServletServerContainerFactoryBean webSocketContainer() {
        var container=new ServletServerContainerFactoryBean();
        container.setMaxTextMessageBufferSize(4096); container.setMaxBinaryMessageBufferSize(4096);
        container.setMaxSessionIdleTimeout(60000L); container.setAsyncSendTimeout(1000L);
        return container;
    }
}

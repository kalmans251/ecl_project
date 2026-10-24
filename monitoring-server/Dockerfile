FROM maven:3.9.11-eclipse-temurin-17 AS build
WORKDIR /app
COPY pom.xml .
COPY src src
RUN mvn -B -ntp verify
FROM eclipse-temurin:17-jre
WORKDIR /app
RUN mkdir /app/data && chown -R 10001:10001 /app
COPY --from=build /app/target/monitoring-server-0.1.0.jar /app/server.jar
USER 10001:10001
EXPOSE 8080
ENTRYPOINT ["java", "-jar", "/app/server.jar"]

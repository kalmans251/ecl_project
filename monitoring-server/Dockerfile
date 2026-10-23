FROM maven:3.9.11-eclipse-temurin-17 AS build
RUN apt-get update && apt-get install -y --no-install-recommends cmake ninja-build gcc git libc6-dev && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY pom.xml .
COPY src src
COPY native native
RUN mvn -B -ntp -Pnative-codec verify
FROM eclipse-temurin:17-jre
WORKDIR /app
RUN mkdir /app/data && chown -R 10001:10001 /app
COPY --from=build /app/target/monitoring-server-0.1.0.jar /app/server.jar
USER 10001:10001
EXPOSE 8080
ENTRYPOINT ["java", "-jar", "/app/server.jar"]

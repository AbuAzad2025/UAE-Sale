#!/bin/bash
# SSL/HTTPS Setup Script using Let's Encrypt

# Colors
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

echo -e "${GREEN}🔒 SSL/HTTPS Setup for Garage Management System${NC}"
echo "=================================================="
echo ""

# Check if running as root
if [ "$EUID" -ne 0 ]; then 
    echo -e "${RED}Please run as root (sudo)${NC}"
    exit 1
fi

# Get domain name
read -p "Enter your domain name (e.g., garage.example.com): " DOMAIN
read -p "Enter admin email: " EMAIL

if [ -z "$DOMAIN" ] || [ -z "$EMAIL" ]; then
    echo -e "${RED}Domain and email are required!${NC}"
    exit 1
fi

echo ""
echo -e "${YELLOW}Setting up SSL for: $DOMAIN${NC}"
echo -e "${YELLOW}Admin email: $EMAIL${NC}"
echo ""

# Create SSL directory
mkdir -p ssl
chmod 755 ssl

# Install certbot if not installed
if ! command -v certbot &> /dev/null; then
    echo -e "${YELLOW}Installing certbot...${NC}"
    
    # For Ubuntu/Debian
    if command -v apt-get &> /dev/null; then
        apt-get update
        apt-get install -y certbot python3-certbot-nginx
    # For CentOS/RHEL
    elif command -v yum &> /dev/null; then
        yum install -y certbot python3-certbot-nginx
    else
        echo -e "${RED}Please install certbot manually${NC}"
        exit 1
    fi
fi

# Obtain SSL certificate
echo -e "${GREEN}Obtaining SSL certificate from Let's Encrypt...${NC}"

certbot certonly \
    --standalone \
    --preferred-challenges http \
    --email $EMAIL \
    --agree-tos \
    --no-eff-email \
    -d $DOMAIN

if [ $? -eq 0 ]; then
    echo -e "${GREEN}✅ SSL certificate obtained successfully!${NC}"
    
    # Create symbolic links
    ln -sf /etc/letsencrypt/live/$DOMAIN ssl/live
    
    # Update nginx config with domain
    sed -i "s/yourdomain.com/$DOMAIN/g" nginx-ssl.conf
    
    # Update docker-compose
    sed -i "s/yourdomain.com/$DOMAIN/g" docker-compose.prod.yml
    
    # Create .env if not exists
    if [ ! -f .env ]; then
        cp .env.production .env
        echo -e "${YELLOW}⚠️  Created .env file - Please update it with your values!${NC}"
    fi
    
    echo ""
    echo -e "${GREEN}Setup Complete!${NC}"
    echo ""
    echo "Next steps:"
    echo "1. Update .env file with your configuration"
    echo "2. Run: docker-compose -f docker-compose.prod.yml up -d"
    echo "3. Your site will be available at: https://$DOMAIN"
    echo ""
    echo "To renew certificate (auto-renewal recommended):"
    echo "certbot renew --dry-run"
    echo ""
    echo "Add to crontab for auto-renewal:"
    echo "0 3 * * * certbot renew --quiet --post-hook 'docker-compose -f /path/to/docker-compose.prod.yml restart nginx'"
    
else
    echo -e "${RED}❌ Failed to obtain SSL certificate${NC}"
    echo "Please check:"
    echo "1. Domain DNS points to this server"
    echo "2. Port 80 is open"
    echo "3. No other service is using port 80"
    exit 1
fi

